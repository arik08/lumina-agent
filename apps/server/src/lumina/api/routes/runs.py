from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...agent.executor import local_run_executor
from ...auth import resolve_server_session
from ...config import Settings, get_settings
from ...db import SessionLocal, get_db
from ...models import RunEvent, User
from ...runs.broker import event_broker
from ...runs.service import (
    apply_run_action,
    command_payload,
    create_run,
    event_response,
    message_response,
    plan_snapshot,
    run_for_user,
    run_snapshot,
    run_snapshots,
    runs_for_user,
)
from ...runs.state import TERMINAL_STATUSES
from ..dependencies import (
    AuthContext,
    get_current_user,
    get_stream_auth_context,
    require_csrf,
)
from ..errors import ApiProblem
from ..schemas import RunActionRequest, RunCreate


router = APIRouter(tags=["runs"])
stream_router = APIRouter(tags=["run-stream"])


def _idempotency_key(value: str | None) -> str:
    if value is None or not (8 <= len(value) <= 200):
        raise ApiProblem(
            400,
            "idempotency_key_required",
            "안전한 재시도를 위해 Idempotency-Key가 필요합니다.",
        )
    return value


@router.post("/conversations/{conversation_id}/runs", status_code=202)
async def post_run(
    conversation_id: str,
    payload: RunCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    run, message, created = create_run(
        db,
        user=context.user,
        conversation_id=conversation_id,
        payload=payload,
        idempotency_key=_idempotency_key(idempotency_key),
        image_backend_model=settings.codex_image_model,
        settings=settings,
    )
    db.commit()
    if created:
        local_run_executor.enqueue(run.id)
        await event_broker.notify(run.id)
    return {
        "message": message_response(message, db),
        "command": None,
        "run": run_snapshot(db, run),
    }


@router.post("/runs/{run_id}/actions")
async def post_run_action(
    run_id: str,
    payload: RunActionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    run, command, message, changed = apply_run_action(
        db,
        user=context.user,
        run_id=run_id,
        payload=payload,
        idempotency_key=_idempotency_key(idempotency_key),
    )
    db.commit()
    if changed:
        local_run_executor.invalidate_control(run.id)
        if payload.type == "cancel":
            local_run_executor.cancel(run.id)
        if payload.type in {"resume", "retry_step", "submit_user_input"} or (
            payload.type in {"approve", "reject"} and run.status == "queued"
        ):
            local_run_executor.enqueue(run.id)
        if payload.type == "resume" and run.status == "queued":
            await event_broker.replace_assistant_draft(
                run.id,
                str(run.snapshot_json.get("assistant_message_id", "")),
                run.assistant_draft,
            )
        await event_broker.notify(run.id)
    return {
        "message": message_response(message, db) if message else None,
        "command": command_payload(command),
        "run": run_snapshot(db, run),
    }


@router.get("/runs/{run_id}/snapshot")
def get_run_snapshot(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    run = run_for_user(db, user, run_id)
    return run_snapshot(db, run)


@router.post("/runs/snapshots")
def post_run_snapshots(
    payload: dict[str, object],
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> list[dict[str, object]]:
    raw_run_ids = payload.get("runIds")
    if not isinstance(raw_run_ids, list) or not 1 <= len(raw_run_ids) <= 20:
        raise ApiProblem(
            422,
            "invalid_run_ids",
            "Run snapshot은 한 번에 1개 이상 20개 이하로 요청해야 합니다.",
        )
    run_ids = list(dict.fromkeys(str(item) for item in raw_run_ids if item))
    if len(run_ids) != len(raw_run_ids):
        raise ApiProblem(422, "invalid_run_ids", "Run ID가 올바르지 않습니다.")
    runs = runs_for_user(db, context.user, run_ids)
    return run_snapshots(db, runs)


@router.get("/runs/{run_id}/plan")
def get_run_plan(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    run = run_for_user(db, user, run_id)
    plan = plan_snapshot(db, run)
    if plan is None:
        raise ApiProblem(404, "plan_not_found", "Run의 Plan을 찾을 수 없습니다.")
    return plan


@stream_router.get("/stream/runs/{run_id}", include_in_schema=False)
async def stream_run(
    run_id: str,
    request: Request,
    after_sequence: int = 0,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    context: AuthContext = Depends(get_stream_auth_context),
    db: Session = Depends(get_db, scope="function"),
) -> StreamingResponse:
    run_for_user(db, context.user, run_id)
    cursor = max(0, after_sequence)
    if last_event_id:
        try:
            cursor = max(cursor, int(last_event_id))
        except ValueError as exc:
            raise ApiProblem(
                400, "invalid_event_cursor", "Event cursor가 올바르지 않습니다."
            ) from exc

    async def events() -> AsyncIterator[str]:
        nonlocal cursor
        progress_revision = 0
        assistant_draft_revision = 0
        wake_revision, durable_revision = event_broker.revisions(run_id)
        query_required = True
        while True:
            if await request.is_disconnected():
                return
            if query_required:
                observed_durable_revision = event_broker.revisions(run_id)[1]
                with SessionLocal() as event_db:
                    resolved = resolve_server_session(event_db, context.session_token)
                    if resolved is None:
                        return
                    try:
                        run = run_for_user(event_db, resolved.user, run_id)
                    except ApiProblem:
                        return
                    rows = list(
                        event_db.scalars(
                            select(RunEvent)
                            .where(RunEvent.run_id == run_id, RunEvent.sequence > cursor)
                            .order_by(RunEvent.sequence)
                            .limit(200)
                        )
                    )
                    terminal = run.status in TERMINAL_STATUSES
                    last_sequence = run.last_sequence
                    encoded = [event_response(event) for event in rows]
                durable_revision = max(durable_revision, observed_durable_revision)
                if encoded:
                    for event in encoded:
                        cursor = int(event["sequence"])
                        data = json.dumps(
                            jsonable_encoder(event),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        yield f"id: {cursor}\nevent: run_event\ndata: {data}\n\n"
                    continue
                if terminal and cursor >= last_sequence:
                    event_broker.clear_artifact_progress(run_id)
                    event_broker.clear_assistant_draft(run_id)
                    return
            delivered_transient = False
            transient_draft = event_broker.latest_assistant_draft(
                run_id, after_revision=assistant_draft_revision
            )
            if transient_draft is not None:
                assistant_draft_revision, draft = transient_draft
                data = json.dumps(
                    {"runId": run_id, "draft": draft},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"event: assistant_draft\ndata: {data}\n\n"
                delivered_transient = True
            transient_progress = event_broker.latest_artifact_progress(
                run_id, after_revision=progress_revision
            )
            if transient_progress is not None:
                progress_revision, progress = transient_progress
                data = json.dumps(
                    {"runId": run_id, "progress": progress},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"event: artifact_progress\ndata: {data}\n\n"
                delivered_transient = True
            if not delivered_transient:
                yield ": keep-alive\n\n"
            wake_revision, timed_out = await event_broker.wait(
                run_id,
                timeout=10.0,
                after_revision=wake_revision,
            )
            current_durable_revision = event_broker.revisions(run_id)[1]
            query_required = timed_out or current_durable_revision > durable_revision

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
