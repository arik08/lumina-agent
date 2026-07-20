from __future__ import annotations

from collections import defaultdict
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.orm import Session

from ...agent_frontends import agent_frontend_payload
from ...artifact_citations import run_artifact_citation_texts
from ...audit import record_audit
from ...authorization import require_conversation
from ...citations import resolve_inline_citations
from ...config import Settings, get_settings
from ...conversations.service import (
    branch_conversation,
    conversation_summaries,
    conversation_summary,
    create_conversation,
    list_conversations,
    move_conversation,
    search_conversation_content,
    soft_delete_conversation,
    update_conversation,
)
from ...db import get_db
from ...models import (
    Artifact,
    ArtifactVersion,
    Attachment,
    Message,
    MessageReference,
    Run,
    ToolExecution,
    User,
)
from ...runs.service import message_response, preload_message_attachments, run_snapshots
from ...storage import ManagedLocalStorage
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem
from ..schemas import (
    ConversationBranch,
    ConversationCreate,
    ConversationMove,
    ConversationPatch,
)


router = APIRouter(prefix="/conversations", tags=["conversations"])


def _usage_number(usage: dict[str, object], key: str) -> float:
    value = usage.get(key)
    return (
        float(value)
        if isinstance(value, int | float) and not isinstance(value, bool)
        else 0.0
    )


def _add_usage(
    left: dict[str, object] | None,
    right: dict[str, object],
) -> dict[str, object]:
    input_tokens = int(_usage_number(right, "input_tokens"))
    cached_tokens = int(_usage_number(right, "cached_input_tokens"))
    normalized_right: dict[str, object] = {
        **right,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "cache_write_tokens": int(_usage_number(right, "cache_write_tokens")),
        "uncached_input_tokens": int(
            _usage_number(right, "uncached_input_tokens")
            if "uncached_input_tokens" in right
            else max(0, input_tokens - cached_tokens)
        ),
        "output_tokens": int(_usage_number(right, "output_tokens")),
    }
    if left is None:
        return normalized_right
    result = {
        **normalized_right,
        **{
            key: int(_usage_number(left, key))
            + int(_usage_number(normalized_right, key))
            for key in (
                "input_tokens",
                "cached_input_tokens",
                "cache_write_tokens",
                "uncached_input_tokens",
                "output_tokens",
            )
        },
    }
    if "cost_usd" in left and "cost_usd" in normalized_right:
        result["cost_usd"] = _usage_number(left, "cost_usd") + _usage_number(
            normalized_right, "cost_usd"
        )
    else:
        result.pop("cost_usd", None)
    left_breakdown = left.get("estimated_cost_breakdown_usd")
    right_breakdown = normalized_right.get("estimated_cost_breakdown_usd")
    if isinstance(left_breakdown, dict) and isinstance(right_breakdown, dict):
        result["estimated_cost_breakdown_usd"] = {
            key: _usage_number(left_breakdown, key)
            + _usage_number(right_breakdown, key)
            for key in ("cached_input", "uncached_input", "input", "output", "total")
        }
    else:
        result.pop("estimated_cost_breakdown_usd", None)
    result["cost_basis"] = (
        normalized_right.get("cost_basis")
        if left.get("cost_basis") == normalized_right.get("cost_basis")
        else "mixed"
    )
    return result


def _message_response_with_artifact_citations(
    message: Message,
    db: Session,
    artifact_texts_by_run: dict[str, tuple[str, ...]],
    attachments_by_message: dict[str, list[dict[str, object]]] | None = None,
) -> dict[str, object]:
    payload = message_response(
        message,
        db,
        preloaded_attachments=(attachments_by_message or {}).get(message.id),
    )
    metadata = message.metadata_json or {}
    sources = metadata.get("sources")
    if (
        message.role == "assistant"
        and message.run_id is not None
        and isinstance(sources, list)
        and sources
        and not metadata.get("citations")
        and artifact_texts_by_run.get(message.run_id)
    ):
        payload["metadata"] = {
            **metadata,
            **resolve_inline_citations(
                message.canonical_text,
                sources,
                reference_texts=artifact_texts_by_run[message.run_id],
            ),
        }
    return payload


def _summary(
    db: Session,
    conversation,
    result: dict[str, object] | None = None,
) -> dict[str, object]:
    result = result or conversation_summary(db, conversation)
    result["revision"] = str(result["revision"])
    return {
        "id": result["id"],
        "projectId": result["project_id"],
        "title": result["title"],
        "isFavorite": result["is_favorite"],
        "isLiked": result["is_liked"],
        "lastRunStatus": result["last_run_status"],
        "activeRunId": result["active_run_id"],
        "lastSequence": result["last_sequence"],
        "parentConversationId": conversation.parent_conversation_id,
        "branchMessageId": conversation.branch_message_id,
        "agent": agent_frontend_payload(
            conversation.agent_id, conversation.agent_version
        ),
        "revision": result["revision"],
        "createdAt": result["created_at"],
        "updatedAt": result["updated_at"],
    }


@router.get("")
def get_conversations(
    project_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    conversations, next_cursor = list_conversations(
        db, user, project_id=project_id, cursor=cursor, limit=limit
    )
    summaries = conversation_summaries(db, conversations)
    return {
        "items": [
            _summary(db, conversation, summaries[conversation.id])
            for conversation in conversations
        ],
        "nextCursor": next_cursor,
        "hasMore": next_cursor is not None,
    }


@router.get("/search")
def search_conversations(
    title_query: str = "",
    project_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    conversations, next_cursor = list_conversations(
        db,
        user,
        project_id=project_id,
        title_query=title_query,
        cursor=cursor,
        limit=limit,
    )
    summaries = conversation_summaries(db, conversations)
    return {
        "items": [
            _summary(db, conversation, summaries[conversation.id])
            for conversation in conversations
        ],
        "nextCursor": next_cursor,
        "hasMore": next_cursor is not None,
    }


@router.get("/content-search")
def search_conversation_messages(
    q: str = Query(default="", max_length=500),
    project_id: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    conversations, tokens = search_conversation_content(
        db,
        user,
        query_text=q,
        project_id=project_id,
        limit=limit,
    )
    conversation_ids = [conversation.id for conversation in conversations]
    matched_by_conversation: dict[str, list[Message]] = defaultdict(list)
    if tokens and conversation_ids:
        predicate = None
        for token in tokens:
            token_predicate = func.lower(Message.canonical_text).contains(token)
            predicate = (
                token_predicate if predicate is None else predicate & token_predicate
            )
        assert predicate is not None
        ranked_matches = (
            select(
                Message.id.label("message_id"),
                func.row_number()
                .over(
                    partition_by=Message.conversation_id,
                    order_by=(Message.created_at.desc(), Message.id),
                )
                .label("rank"),
            )
            .where(
                Message.conversation_id.in_(conversation_ids),
                predicate,
            )
            .subquery()
        )
        for message in db.scalars(
            select(Message)
            .join(ranked_matches, ranked_matches.c.message_id == Message.id)
            .where(ranked_matches.c.rank <= 3)
            .order_by(Message.conversation_id, Message.created_at.desc(), Message.id)
        ):
            matched_by_conversation[message.conversation_id].append(message)
    summaries = conversation_summaries(db, conversations)
    items: list[dict[str, object]] = []
    for conversation in conversations:
        message_matches = [
            {
                "messageId": message.id,
                "role": message.role,
                "snippet": _search_snippet(message.canonical_text, tokens),
                "createdAt": message.created_at,
            }
            for message in matched_by_conversation[conversation.id]
        ]
        item = _summary(db, conversation, summaries[conversation.id])
        item["matches"] = message_matches
        items.append(item)
    return {"items": items, "queryTokens": list(tokens)}


@router.post("", status_code=201)
def post_conversation(
    payload: ConversationCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    conversation = create_conversation(
        db,
        context.user,
        project_id=payload.project_id,
        title=payload.title,
    )
    record_audit(
        db,
        action="conversation_created",
        target_type="conversation",
        target_id=conversation.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return _summary(db, conversation)


def _parse_revision(if_match: str | None) -> int | None:
    if if_match is None:
        return None
    value = if_match.strip().removeprefix("W/").strip('"')
    try:
        revision = int(value)
    except ValueError as exc:
        raise ApiProblem(
            400, "invalid_revision", "대화 revision이 올바르지 않습니다."
        ) from exc
    if revision < 1:
        raise ApiProblem(400, "invalid_revision", "대화 revision이 올바르지 않습니다.")
    return revision


@router.patch("/{conversation_id}")
def patch_conversation(
    conversation_id: str,
    payload: ConversationPatch,
    if_match: str | None = Header(default=None, alias="If-Match"),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    header_revision = _parse_revision(if_match)
    conversation = update_conversation(
        db,
        context.user,
        conversation_id,
        expected_revision=(
            header_revision
            if header_revision is not None
            else payload.expected_revision
        ),
        title=payload.title,
        is_favorite=payload.is_favorite,
        is_liked=payload.is_liked,
        archived=payload.archived,
    )
    db.commit()
    return _summary(db, conversation)


@router.post("/{conversation_id}/move")
def post_move_conversation(
    conversation_id: str,
    payload: ConversationMove,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    conversation = move_conversation(
        db, context.user, conversation_id, payload.project_id
    )
    record_audit(
        db,
        action="conversation_moved",
        target_type="conversation",
        target_id=conversation.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"project_id": payload.project_id},
    )
    db.commit()
    return _summary(db, conversation)


@router.post("/{conversation_id}/branch", status_code=201)
def post_branch_conversation(
    conversation_id: str,
    payload: ConversationBranch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    conversation = branch_conversation(
        db,
        context.user,
        conversation_id,
        anchor_message_id=payload.anchor_message_id,
        title=payload.title,
    )
    record_audit(
        db,
        action="conversation_branched",
        target_type="conversation",
        target_id=conversation.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={
            "parent_conversation_id": conversation_id,
            "anchor_message_id": payload.anchor_message_id,
        },
    )
    db.commit()
    return _summary(db, conversation)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    soft_delete_conversation(db, context.user, conversation_id)
    db.commit()
    return Response(status_code=204)


@router.get("/{conversation_id}/turn-sets")
def get_turn_sets(
    conversation_id: str,
    before_cursor: str | None = None,
    limit_turn_sets: int = Query(default=3, ge=1, le=20),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    conversation = require_conversation(db, user, conversation_id)
    total_question_count = (
        db.scalar(
            select(func.count(Message.id)).where(
                Message.conversation_id == conversation.id,
                Message.role == "user",
                func.trim(Message.canonical_text) != "",
            )
        )
        or 0
    )
    branch_run_id = Message.metadata_json["branchSourceRunId"].as_string()
    turn_key = case(
        (Message.run_id.is_not(None), Message.run_id),
        (
            branch_run_id.is_not(None) & (branch_run_id != ""),
            literal("branch:") + branch_run_id,
        ),
        else_=literal("message:") + Message.id,
    )
    grouped_turns = (
        select(
            turn_key.label("turn_key"),
            func.min(Message.created_at).label("first_created_at"),
            func.min(Message.id).label("first_message_id"),
        )
        .where(Message.conversation_id == conversation.id)
        .group_by(turn_key)
        .subquery()
    )
    page_query = select(
        grouped_turns.c.turn_key,
        grouped_turns.c.first_created_at,
        grouped_turns.c.first_message_id,
    )
    if before_cursor is not None:
        cursor_row = db.execute(
            select(
                grouped_turns.c.first_created_at,
                grouped_turns.c.first_message_id,
            ).where(grouped_turns.c.turn_key == before_cursor)
        ).one_or_none()
        if cursor_row is None:
            raise ApiProblem(
                400,
                "invalid_turn_cursor",
                "대화 기록 cursor가 올바르지 않습니다.",
            )
        cursor_created_at, cursor_message_id = cursor_row
        page_query = page_query.where(
            or_(
                grouped_turns.c.first_created_at < cursor_created_at,
                (
                    (grouped_turns.c.first_created_at == cursor_created_at)
                    & (grouped_turns.c.first_message_id < cursor_message_id)
                ),
            )
        )
    page_rows = list(
        db.execute(
            page_query.order_by(
                grouped_turns.c.first_created_at.desc(),
                grouped_turns.c.first_message_id.desc(),
            ).limit(limit_turn_sets + 1)
        )
    )
    has_more = len(page_rows) > limit_turn_sets
    selected_rows = list(reversed(page_rows[:limit_turn_sets]))
    selected_keys = [str(row.turn_key) for row in selected_rows]
    usage_before_page: dict[str, object] | None = None
    if selected_rows:
        oldest = selected_rows[0]
        older_turn = or_(
            grouped_turns.c.first_created_at < oldest.first_created_at,
            (
                (grouped_turns.c.first_created_at == oldest.first_created_at)
                & (grouped_turns.c.first_message_id < oldest.first_message_id)
            ),
        )
        input_tokens = Run.usage_json["input_tokens"].as_integer()
        cached_tokens = Run.usage_json["cached_input_tokens"].as_integer()
        cache_write_tokens = Run.usage_json["cache_write_tokens"].as_integer()
        uncached_tokens = Run.usage_json["uncached_input_tokens"].as_integer()
        output_tokens = Run.usage_json["output_tokens"].as_integer()
        cost_usd = Run.usage_json["cost_usd"].as_float()
        cost_basis = Run.usage_json["cost_basis"].as_string()
        breakdown = Run.usage_json["estimated_cost_breakdown_usd"]
        aggregate = db.execute(
            select(
                func.count(Run.id),
                func.sum(func.coalesce(input_tokens, 0)),
                func.sum(func.coalesce(cached_tokens, 0)),
                func.sum(func.coalesce(cache_write_tokens, 0)),
                func.sum(
                    func.coalesce(
                        uncached_tokens,
                        func.coalesce(input_tokens, 0)
                        - func.coalesce(cached_tokens, 0),
                    )
                ),
                func.sum(func.coalesce(output_tokens, 0)),
                func.count(cost_usd),
                func.sum(cost_usd),
                func.min(cost_basis),
                func.max(cost_basis),
                *[
                    func.sum(func.coalesce(breakdown[key].as_float(), 0.0))
                    for key in (
                        "cached_input",
                        "uncached_input",
                        "input",
                        "output",
                        "total",
                    )
                ],
                func.count(breakdown["total"].as_float()),
            )
            .select_from(Run)
            .join(grouped_turns, grouped_turns.c.turn_key == Run.id)
            .where(
                Run.conversation_id == conversation.id,
                older_turn,
            )
        ).one()
        (
            usage_count,
            input_total,
            cached_total,
            cache_write_total,
            uncached_total,
            output_total,
            cost_count,
            cost_total,
            basis_min,
            basis_max,
            cached_cost,
            uncached_cost,
            input_cost,
            output_cost,
            breakdown_total,
            breakdown_count,
        ) = aggregate
        if usage_count:
            usage_before_page = {
                "input_tokens": int(input_total or 0),
                "cached_input_tokens": int(cached_total or 0),
                "cache_write_tokens": int(cache_write_total or 0),
                "uncached_input_tokens": max(0, int(uncached_total or 0)),
                "output_tokens": int(output_total or 0),
                "cost_basis": basis_min if basis_min == basis_max else "mixed",
            }
            if cost_count == usage_count:
                usage_before_page["cost_usd"] = float(cost_total or 0.0)
            if breakdown_count == usage_count:
                usage_before_page["estimated_cost_breakdown_usd"] = {
                    "cached_input": float(cached_cost or 0.0),
                    "uncached_input": float(uncached_cost or 0.0),
                    "input": float(input_cost or 0.0),
                    "output": float(output_cost or 0.0),
                    "total": float(breakdown_total or 0.0),
                }
    selected_messages = (
        list(
            db.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation.id,
                    turn_key.in_(selected_keys),
                )
                .order_by(Message.created_at, Message.id)
            )
        )
        if selected_keys
        else []
    )
    grouped: dict[str, list[Message]] = defaultdict(list)
    for message in selected_messages:
        branch_source_run_id = (message.metadata_json or {}).get("branchSourceRunId")
        key = message.run_id or (
            f"branch:{branch_source_run_id}"
            if isinstance(branch_source_run_id, str) and branch_source_run_id
            else f"message:{message.id}"
        )
        grouped[key].append(message)
    legacy_citation_run_ids = [
        message.run_id
        for message in selected_messages
        if message.role == "assistant"
        and message.run_id is not None
        and isinstance((message.metadata_json or {}).get("sources"), list)
        and (message.metadata_json or {}).get("sources")
        and not (message.metadata_json or {}).get("citations")
    ]
    artifact_texts_by_run = (
        run_artifact_citation_texts(
            db, ManagedLocalStorage(settings.artifacts_dir), legacy_citation_run_ids
        )
        if settings.artifacts_dir is not None and legacy_citation_run_ids
        else {}
    )
    attachments_by_message = preload_message_attachments(db, selected_messages)
    selected_run_ids = [
        key for key in selected_keys if not key.startswith(("message:", "branch:"))
    ]
    selected_runs = (
        list(db.scalars(select(Run).where(Run.id.in_(selected_run_ids))))
        if selected_run_ids
        else []
    )
    runs_by_id = {run.id: run for run in selected_runs}
    snapshots_by_run = {
        snapshot["runId"]: snapshot for snapshot in run_snapshots(db, selected_runs)
    }
    turn_sets: list[dict[str, object]] = []
    for key in selected_keys:
        run = runs_by_id.get(key)
        snapshot = snapshots_by_run.get(key)
        group = grouped[key]
        turn_sets.append(
            {
                "id": key,
                "runId": run.id if run else None,
                "messages": [
                    _message_response_with_artifact_citations(
                        message,
                        db,
                        artifact_texts_by_run,
                        attachments_by_message,
                    )
                    for message in group
                ],
                "plan": snapshot["plan"] if snapshot else None,
                "toolExecutions": snapshot["toolExecutions"] if snapshot else [],
                "artifacts": snapshot["artifacts"] if snapshot else [],
                "createdAt": group[0].created_at,
                "completedAt": run.finished_at if run else group[-1].updated_at,
            }
        )
    return {
        "turnSets": turn_sets,
        "runSnapshots": list(snapshots_by_run.values()),
        "previousCursor": selected_keys[0] if has_more and selected_keys else None,
        "hasMoreBefore": has_more,
        "totalQuestionCount": total_question_count,
        "usageBeforePage": usage_before_page or {},
    }


@router.get("/{conversation_id}/runs/{run_id}/sources/{source_id}/content")
def get_web_source_content(
    conversation_id: str,
    run_id: str,
    source_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=4_000, ge=500, le=20_000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    conversation = require_conversation(db, user, conversation_id)
    run = db.get(Run, run_id)
    if run is None or run.conversation_id != conversation.id:
        raise ApiProblem(404, "source_not_found", "출처 본문을 찾을 수 없습니다.")

    tools = db.scalars(
        select(ToolExecution).where(
            ToolExecution.run_id == run.id,
            ToolExecution.tool_name == "web_fetch",
            ToolExecution.status == "completed",
        )
    )
    for tool in tools:
        result = tool.result_json if isinstance(tool.result_json, dict) else {}
        source = result.get("source")
        text = result.get("text")
        if (
            not isinstance(source, dict)
            or source.get("sourceId") != source_id
            or not isinstance(text, str)
        ):
            continue
        page = text[offset : offset + limit]
        next_offset = offset + len(page)
        raw_llm_chars = result.get("providerContextIncludedChars")
        llm_chars_recorded = isinstance(raw_llm_chars, int) and not isinstance(
            raw_llm_chars, bool
        )
        llm_chars = raw_llm_chars if llm_chars_recorded else min(len(text), 15_000)
        return {
            "sourceId": source_id,
            "content": page,
            "offset": offset,
            "nextOffset": next_offset,
            "hasMore": next_offset < len(text),
            "totalChars": len(text),
            "llmTextChars": llm_chars,
            "llmTextCharsEstimated": not llm_chars_recorded,
        }
    raise ApiProblem(404, "source_not_found", "출처 본문을 찾을 수 없습니다.")


@router.get("/{conversation_id}/export")
def export_conversation(
    conversation_id: str,
    request: Request,
    format: str = Query(default="json", pattern="^(json|markdown)$"),
    include_artifacts: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    conversation = require_conversation(db, user, conversation_id)
    messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at, Message.id)
        )
    )
    message_ids = [message.id for message in messages]
    references_by_message: dict[str, list[dict[str, object]]] = defaultdict(list)
    if message_ids:
        for reference in db.scalars(
            select(MessageReference).where(MessageReference.message_id.in_(message_ids))
        ):
            references_by_message[reference.message_id].append(
                {
                    "kind": reference.kind,
                    "referenceId": reference.reference_id,
                    "versionOrDigest": reference.version_or_digest,
                    "displaySnapshot": reference.display_snapshot_json,
                    "validationStatus": reference.validation_status,
                }
            )
    runs = list(
        db.scalars(
            select(Run)
            .where(Run.conversation_id == conversation.id)
            .order_by(Run.created_at, Run.id)
        )
    )
    run_ids = [run.id for run in runs]
    tools = (
        list(
            db.scalars(
                select(ToolExecution)
                .where(ToolExecution.run_id.in_(run_ids))
                .order_by(ToolExecution.created_at, ToolExecution.id)
            )
        )
        if run_ids
        else []
    )
    attachments = list(
        db.scalars(
            select(Attachment)
            .where(
                Attachment.conversation_id == conversation.id,
                Attachment.deleted_at.is_(None),
            )
            .order_by(Attachment.created_at, Attachment.id)
        )
    )
    artifacts = (
        list(
            db.scalars(
                select(Artifact)
                .where(
                    Artifact.conversation_id == conversation.id,
                    Artifact.deleted_at.is_(None),
                )
                .order_by(Artifact.created_at, Artifact.id)
            )
        )
        if include_artifacts
        else []
    )
    artifact_versions: dict[str, list[ArtifactVersion]] = defaultdict(list)
    if artifacts:
        for version in db.scalars(
            select(ArtifactVersion)
            .where(ArtifactVersion.artifact_id.in_([item.id for item in artifacts]))
            .order_by(ArtifactVersion.artifact_id, ArtifactVersion.version_number)
        ):
            artifact_versions[version.artifact_id].append(version)

    document: dict[str, object] = {
        "schemaVersion": "lumina.conversation-export.v1",
        "conversation": {
            "id": conversation.id,
            "projectId": conversation.project_id,
            "title": conversation.title,
            "parentConversationId": conversation.parent_conversation_id,
            "branchMessageId": conversation.branch_message_id,
            "createdAt": conversation.created_at,
            "updatedAt": conversation.updated_at,
        },
        "messages": [
            {
                "id": message.id,
                "runId": message.run_id,
                "role": message.role,
                "status": message.status,
                "text": message.canonical_text,
                "turnIndex": message.turn_index,
                "metadata": message.metadata_json,
                "references": references_by_message.get(message.id, []),
                "createdAt": message.created_at,
            }
            for message in messages
        ],
        "runs": [
            {
                "id": run.id,
                "status": run.status,
                "providerId": run.provider_id,
                "modelKey": run.model_key,
                "effort": run.effort,
                "snapshot": run.snapshot_json,
                "usage": run.usage_json,
                "createdAt": run.created_at,
                "startedAt": run.started_at,
                "finishedAt": run.finished_at,
            }
            for run in runs
        ],
        "toolExecutions": [
            {
                "id": tool.id,
                "runId": tool.run_id,
                "toolCallId": tool.tool_call_id,
                "toolName": tool.tool_name,
                "status": tool.status,
                "input": tool.validated_input_json,
                "result": tool.result_json,
                "errorCode": tool.error_code,
                "createdAt": tool.created_at,
                "finishedAt": tool.finished_at,
            }
            for tool in tools
        ],
        "attachments": [
            {
                "id": attachment.id,
                "filename": attachment.original_filename,
                "mimeType": attachment.sniffed_mime_type,
                "sizeBytes": attachment.size_bytes,
                "contentHash": attachment.content_hash,
                "status": attachment.status,
                "createdAt": attachment.created_at,
            }
            for attachment in attachments
        ],
        "artifacts": [
            {
                "id": artifact.id,
                "displayName": artifact.display_name,
                "kind": artifact.kind,
                "mimeType": artifact.mime_type,
                "currentVersion": artifact.current_version_number,
                "versions": [
                    {
                        "version": version.version_number,
                        "contentHash": version.content_hash,
                        "sizeBytes": version.size_bytes,
                        "validationStatus": version.validation_status,
                        "createdAt": version.created_at,
                    }
                    for version in artifact_versions.get(artifact.id, [])
                ],
            }
            for artifact in artifacts
        ],
    }
    record_audit(
        db,
        action="conversation_exported",
        target_type="conversation",
        target_id=conversation.id,
        result="success",
        actor=user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"format": format, "include_artifacts": include_artifacts},
    )
    db.commit()

    filename = quote(_export_filename(conversation.title, format), safe="")
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    if format == "markdown":
        return Response(
            content=_markdown_export(document),
            media_type="text/markdown; charset=utf-8",
            headers=headers,
        )
    content = json.dumps(
        jsonable_encoder(document), ensure_ascii=False, indent=2
    ).encode("utf-8")
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers=headers,
    )


def _export_filename(title: str, format: str) -> str:
    clean = "".join(
        character if character.isalnum() or character in {"-", "_", " "} else "_"
        for character in title
    ).strip()[:80]
    return f"{clean or 'conversation'}.{'md' if format == 'markdown' else 'json'}"


def _markdown_export(document: dict[str, object]) -> str:
    conversation = document["conversation"]
    assert isinstance(conversation, dict)
    lines = [f"# {conversation['title']}", "", "---", ""]
    messages = document["messages"]
    assert isinstance(messages, list)
    labels = {"user": "사용자", "assistant": "Lumina", "system": "시스템"}
    for item in messages:
        assert isinstance(item, dict)
        role = str(item.get("role", "message"))
        lines.extend(
            [
                f"## {labels.get(role, role)}",
                "",
                str(item.get("text", "")),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _search_snippet(text: str, tokens: tuple[str, ...], radius: int = 90) -> str:
    normalized = text.casefold()
    positions = [normalized.find(token) for token in tokens]
    positions = [position for position in positions if position >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - radius)
    end = min(len(text), center + radius)
    prefix = "…" if start else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"
