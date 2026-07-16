from __future__ import annotations

from collections import defaultdict
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...authorization import require_conversation
from ...conversations.service import (
    branch_conversation,
    conversation_summary,
    create_conversation,
    list_conversations,
    move_conversation,
    recent_messages,
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
from ...runs.service import message_response, run_snapshot
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem
from ..schemas import (
    ConversationBranch,
    ConversationCreate,
    ConversationMove,
    ConversationPatch,
)


router = APIRouter(prefix="/conversations", tags=["conversations"])


def _summary(db: Session, conversation) -> dict[str, object]:
    result = conversation_summary(db, conversation)
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
    return {
        "items": [_summary(db, conversation) for conversation in conversations],
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
    return {
        "items": [_summary(db, conversation) for conversation in conversations],
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
    items: list[dict[str, object]] = []
    for conversation in conversations:
        message_matches = []
        if tokens:
            predicate = None
            for token in tokens:
                token_predicate = func.lower(Message.canonical_text).contains(token)
                predicate = (
                    token_predicate
                    if predicate is None
                    else predicate & token_predicate
                )
            assert predicate is not None
            matched_messages = list(
                db.scalars(
                    select(Message)
                    .where(
                        Message.conversation_id == conversation.id,
                        predicate,
                    )
                    .order_by(Message.created_at.desc(), Message.id)
                    .limit(3)
                )
            )
            message_matches = [
                {
                    "messageId": message.id,
                    "role": message.role,
                    "snippet": _search_snippet(message.canonical_text, tokens),
                    "createdAt": message.created_at,
                }
                for message in matched_messages
            ]
        item = _summary(db, conversation)
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
    db: Session = Depends(get_db),
) -> dict[str, object]:
    conversation = require_conversation(db, user, conversation_id)
    messages = recent_messages(db, conversation.id, limit=400)
    run_order: list[str] = []
    grouped: dict[str, list[Message]] = defaultdict(list)
    for message in messages:
        branch_source_run_id = (message.metadata_json or {}).get("branchSourceRunId")
        key = message.run_id or (
            f"branch:{branch_source_run_id}"
            if isinstance(branch_source_run_id, str) and branch_source_run_id
            else f"message:{message.id}"
        )
        if key not in grouped:
            run_order.append(key)
        grouped[key].append(message)
    end = len(run_order)
    if before_cursor is not None:
        try:
            end = run_order.index(before_cursor)
        except ValueError as exc:
            raise ApiProblem(
                400,
                "invalid_turn_cursor",
                "대화 기록 cursor가 올바르지 않습니다.",
            ) from exc
    start = max(0, end - limit_turn_sets)
    selected_keys = run_order[start:end]
    turn_sets: list[dict[str, object]] = []
    for key in selected_keys:
        run = db.get(Run, key) if not key.startswith(("message:", "branch:")) else None
        snapshot = run_snapshot(db, run) if run else None
        group = grouped[key]
        turn_sets.append(
            {
                "id": key,
                "runId": run.id if run else None,
                "messages": [message_response(message, db) for message in group],
                "plan": snapshot["plan"] if snapshot else None,
                "toolExecutions": snapshot["toolExecutions"] if snapshot else [],
                "artifacts": snapshot["artifacts"] if snapshot else [],
                "createdAt": group[0].created_at,
                "completedAt": run.finished_at if run else group[-1].updated_at,
            }
        )
    has_more = start > 0
    return {
        "turnSets": turn_sets,
        "previousCursor": selected_keys[0] if has_more and selected_keys else None,
        "hasMoreBefore": has_more,
    }


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
