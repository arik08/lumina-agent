from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session

from ...agent.executor import local_run_executor
from ...audit import record_audit
from ...db import get_db
from ...models import User, utc_now
from ...schedules.schemas import ScheduledTaskCreate, ScheduledTaskPatch
from ...schedules.service import (
    archive_scheduled_task,
    create_scheduled_task,
    list_scheduled_runs,
    list_scheduled_tasks,
    require_scheduled_task,
    scheduled_run_payload,
    scheduled_task_payload,
    set_scheduled_task_enabled,
    start_scheduled_run,
    update_scheduled_task,
)
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem


router = APIRouter(prefix="/scheduled-tasks", tags=["scheduled-tasks"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _idempotency_key(value: str | None) -> str:
    if value is None or not 8 <= len(value) <= 128:
        raise ApiProblem(
            400,
            "idempotency_key_required",
            "안전한 재시도를 위해 Idempotency-Key가 필요합니다.",
        )
    return value


@router.get("")
def get_scheduled_tasks(
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        scheduled_task_payload(task)
        for task in list_scheduled_tasks(db, user=user, project_id=project_id)
    ]


@router.post("", status_code=201)
def post_scheduled_task(
    payload: ScheduledTaskCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task = create_scheduled_task(
        db,
        user=context.user,
        project_id=payload.project_id,
        name=payload.name,
        instructions=payload.instructions,
        schedule_kind=payload.schedule_kind,
        schedule_config=payload.schedule_config,
        timezone=payload.timezone,
        context_mode=payload.context_mode,
        source_conversation_id=payload.source_conversation_id,
        execution=payload.execution,
        extension_snapshot_policy=payload.extension_snapshot_policy,
        delivery_policy=payload.delivery_policy,
        enabled=payload.enabled,
        max_attempts=payload.max_attempts,
        timeout_seconds=payload.timeout_seconds,
    )
    record_audit(
        db,
        action="scheduled_task_created",
        target_type="scheduled_task",
        target_id=task.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "project_id": task.project_id,
            "schedule_kind": task.schedule_kind,
            "enabled": task.enabled,
        },
    )
    db.commit()
    return scheduled_task_payload(task)


@router.get("/{task_id}")
def get_scheduled_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return scheduled_task_payload(require_scheduled_task(db, user, task_id))


@router.patch("/{task_id}")
def patch_scheduled_task(
    task_id: str,
    payload: ScheduledTaskPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True, by_alias=False)
    task = update_scheduled_task(
        db,
        user=context.user,
        task_id=task_id,
        changes=changes,
    )
    record_audit(
        db,
        action="scheduled_task_changed",
        target_type="scheduled_task",
        target_id=task.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"changed_fields": sorted(changes)},
    )
    db.commit()
    return scheduled_task_payload(task)


@router.delete("/{task_id}", status_code=204)
def delete_scheduled_task(
    task_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    task = archive_scheduled_task(db, user=context.user, task_id=task_id)
    record_audit(
        db,
        action="scheduled_task_archived",
        target_type="scheduled_task",
        target_id=task.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return Response(status_code=204)


@router.post("/{task_id}/enable")
def post_scheduled_task_enable(
    task_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _set_enabled(db, context, request, task_id, True)


@router.post("/{task_id}/disable")
def post_scheduled_task_disable(
    task_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _set_enabled(db, context, request, task_id, False)


def _set_enabled(
    db: Session,
    context: AuthContext,
    request: Request,
    task_id: str,
    enabled: bool,
) -> dict[str, Any]:
    task = set_scheduled_task_enabled(
        db,
        user=context.user,
        task_id=task_id,
        enabled=enabled,
    )
    record_audit(
        db,
        action="scheduled_task_enabled" if enabled else "scheduled_task_disabled",
        target_type="scheduled_task",
        target_id=task.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return scheduled_task_payload(task)


@router.post("/{task_id}/run-now", status_code=202)
async def post_scheduled_task_run_now(
    task_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    task = require_scheduled_task(db, context.user, task_id, write=True)
    scheduled_run, created = start_scheduled_run(
        db,
        user=context.user,
        task=task,
        trigger_type="manual",
        scheduled_for=utc_now(),
        idempotency_key=_idempotency_key(idempotency_key),
    )
    if created:
        record_audit(
            db,
            action="scheduled_run_started",
            target_type="scheduled_run",
            target_id=scheduled_run.id,
            result="success",
            actor=context.user,
            request_id=_request_id(request),
            metadata={"task_id": task.id, "trigger_type": "manual"},
        )
    db.commit()
    if created and scheduled_run.run_id:
        local_run_executor.enqueue(scheduled_run.run_id)
    return scheduled_run_payload(db, scheduled_run)


@router.get("/{task_id}/runs")
def get_scheduled_task_runs(
    task_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    runs = list_scheduled_runs(db, user=user, task_id=task_id, limit=limit)
    db.commit()
    return [scheduled_run_payload(db, item) for item in runs]
