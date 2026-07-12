from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..authorization import require_conversation
from ..models import (
    Conversation,
    Message,
    MessageFeedback,
    MessageReference,
    MessageSelectionComment,
    ProjectFile,
    Run,
    User,
    utc_now,
)
from ..runs.service import append_event


def require_message(
    db: Session, user: User, message_id: str, *, assistant_only: bool = False
) -> Message:
    message = db.get(Message, message_id)
    if message is None:
        raise ApiProblem(404, "message_not_found", "메시지를 찾을 수 없습니다.")
    require_conversation(db, user, message.conversation_id)
    if assistant_only and message.role != "assistant":
        raise ApiProblem(
            409,
            "assistant_message_required",
            "완료된 assistant 답변에만 이 기능을 사용할 수 있습니다.",
        )
    return message


def append_interaction_event(
    db: Session,
    message: Message,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    if message.run_id is None:
        return
    run = db.get(Run, message.run_id)
    if run is not None and run.conversation_id == message.conversation_id:
        append_event(db, run, event_type, payload)


def synchronize_message_references(
    db: Session, *, user: User, message_id: str
) -> list[MessageReference]:
    message = require_message(db, user, message_id)
    conversation = db.get(Conversation, message.conversation_id)
    raw_references = message.metadata_json.get("prompt_references", [])
    if not isinstance(raw_references, list):
        raw_references = []
    for raw in raw_references:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("kind")
        reference_id = raw.get("reference_id", raw.get("referenceId"))
        if kind not in {"file", "artifact", "skill", "mcp"} or not isinstance(
            reference_id, str
        ):
            continue
        token_start = raw.get("token_start", raw.get("tokenStart"))
        token_end = raw.get("token_end", raw.get("tokenEnd"))
        start = token_start if isinstance(token_start, int) else -1
        end = token_end if isinstance(token_end, int) else None
        existing = db.scalar(
            select(MessageReference).where(
                MessageReference.message_id == message.id,
                MessageReference.kind == kind,
                MessageReference.reference_id == reference_id,
                MessageReference.token_start == start,
            )
        )
        if existing is not None:
            continue
        display = raw.get("display_snapshot", raw.get("displaySnapshot", {}))
        db.add(
            MessageReference(
                message_id=message.id,
                kind=kind,
                reference_id=reference_id,
                version_or_digest=raw.get(
                    "version_or_digest", raw.get("versionOrDigest")
                ),
                token_start=start,
                token_end=end,
                display_snapshot_json=display if isinstance(display, dict) else {},
                validation_status=str(raw.get("validation_status", "valid")),
            )
        )
    db.flush()
    rows = list(
        db.scalars(
            select(MessageReference)
            .where(MessageReference.message_id == message.id)
            .order_by(MessageReference.token_start, MessageReference.created_at)
        )
    )
    for reference in rows:
        if (
            reference.kind != "file"
            or reference.display_snapshot_json.get("targetType") != "project_file"
        ):
            continue
        project_file = db.get(ProjectFile, reference.reference_id)
        reference.validation_status = (
            "valid"
            if project_file is not None
            and project_file.deleted_at is None
            and project_file.status == "active"
            and conversation is not None
            and project_file.project_id == conversation.project_id
            else "unavailable"
        )
    db.flush()
    return rows


def put_rating(
    db: Session, *, user: User, message_id: str, value: str
) -> tuple[Message, MessageFeedback]:
    message = require_message(db, user, message_id, assistant_only=True)
    feedback = db.scalar(
        select(MessageFeedback)
        .where(
            MessageFeedback.message_id == message.id,
            MessageFeedback.user_id == user.id,
            MessageFeedback.kind == "rating",
            MessageFeedback.deleted_at.is_(None),
        )
        .order_by(MessageFeedback.created_at.desc())
    )
    if feedback is None:
        feedback = db.scalar(
            select(MessageFeedback)
            .where(
                MessageFeedback.message_id == message.id,
                MessageFeedback.user_id == user.id,
                MessageFeedback.kind == "rating",
            )
            .order_by(MessageFeedback.created_at.desc())
        )
    if feedback is None:
        feedback = MessageFeedback(
            message_id=message.id,
            user_id=user.id,
            kind="rating",
            rating_value=value,
            status="active",
        )
        db.add(feedback)
    else:
        feedback.rating_value = value
        feedback.status = "active"
        feedback.deleted_at = None
        feedback.updated_at = utc_now()
    db.flush()
    append_interaction_event(
        db,
        message,
        "message_feedback_changed",
        {"messageId": message.id, "feedbackId": feedback.id, "kind": "rating"},
    )
    return message, feedback


def delete_rating(
    db: Session, *, user: User, message_id: str
) -> tuple[Message, MessageFeedback | None]:
    message = require_message(db, user, message_id, assistant_only=True)
    feedback = db.scalar(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message.id,
            MessageFeedback.user_id == user.id,
            MessageFeedback.kind == "rating",
            MessageFeedback.deleted_at.is_(None),
        )
    )
    if feedback is not None:
        feedback.status = "deleted"
        feedback.deleted_at = utc_now()
        feedback.updated_at = feedback.deleted_at
        append_interaction_event(
            db,
            message,
            "message_feedback_changed",
            {
                "messageId": message.id,
                "feedbackId": feedback.id,
                "kind": "rating",
                "deleted": True,
            },
        )
    return message, feedback


def create_report(
    db: Session,
    *,
    user: User,
    message_id: str,
    category: str,
    description: str,
    diagnostic_scope: dict[str, Any],
) -> tuple[Message, MessageFeedback]:
    message = require_message(db, user, message_id, assistant_only=True)
    report = MessageFeedback(
        message_id=message.id,
        user_id=user.id,
        kind="report",
        report_category=category,
        report_description=description or None,
        diagnostic_scope_json=diagnostic_scope,
        status="submitted",
    )
    db.add(report)
    db.flush()
    append_interaction_event(
        db,
        message,
        "message_feedback_changed",
        {"messageId": message.id, "feedbackId": report.id, "kind": "report"},
    )
    return message, report


def list_feedback(
    db: Session, *, user: User, message_id: str
) -> tuple[Message, list[MessageFeedback]]:
    message = require_message(db, user, message_id, assistant_only=True)
    rows = list(
        db.scalars(
            select(MessageFeedback)
            .where(
                MessageFeedback.message_id == message.id,
                MessageFeedback.user_id == user.id,
                MessageFeedback.deleted_at.is_(None),
            )
            .order_by(MessageFeedback.created_at)
        )
    )
    return message, rows


def _message_hash(message: Message) -> str:
    return hashlib.sha256(message.canonical_text.encode("utf-8")).hexdigest()


def _resolve_anchor(
    text: str,
    *,
    start_offset: int,
    end_offset: int,
    selected_text: str,
    prefix_context: str,
    suffix_context: str,
) -> tuple[int, int, str]:
    if (
        0 <= start_offset <= end_offset <= len(text)
        and text[start_offset:end_offset] == selected_text
    ):
        return start_offset, end_offset, "exact"
    candidates: list[tuple[int, int]] = []
    cursor = 0
    while True:
        index = text.find(selected_text, cursor)
        if index < 0:
            break
        end = index + len(selected_text)
        prefix_matches = not prefix_context or text[:index].endswith(prefix_context)
        suffix_matches = not suffix_context or text[end:].startswith(suffix_context)
        if prefix_matches and suffix_matches:
            candidates.append((index, end))
        cursor = index + 1
    if len(candidates) == 1:
        start, end = candidates[0]
        return start, end, "reanchored"
    return start_offset, end_offset, "stale"


def create_comment(
    db: Session,
    *,
    user: User,
    message_id: str,
    block_id: str,
    start_offset: int,
    end_offset: int,
    selected_text: str,
    prefix_context: str,
    suffix_context: str,
    instruction: str,
    status: str,
) -> tuple[Message, MessageSelectionComment]:
    message = require_message(db, user, message_id, assistant_only=True)
    resolved_start, resolved_end, anchor_status = _resolve_anchor(
        message.canonical_text,
        start_offset=start_offset,
        end_offset=end_offset,
        selected_text=selected_text,
        prefix_context=prefix_context,
        suffix_context=suffix_context,
    )
    comment = MessageSelectionComment(
        message_id=message.id,
        author_user_id=user.id,
        source_message_hash=_message_hash(message),
        block_id=block_id,
        start_offset=resolved_start,
        end_offset=resolved_end,
        selected_text=selected_text,
        prefix_context=prefix_context,
        suffix_context=suffix_context,
        instruction=instruction,
        anchor_status=anchor_status,
        status=status,
    )
    db.add(comment)
    db.flush()
    append_interaction_event(
        db,
        message,
        "message_comment_changed",
        {
            "messageId": message.id,
            "commentId": comment.id,
            "status": comment.status,
            "anchorStatus": comment.anchor_status,
        },
    )
    return message, comment


def list_comments(
    db: Session, *, user: User, message_id: str
) -> tuple[Message, list[MessageSelectionComment]]:
    message = require_message(db, user, message_id, assistant_only=True)
    comments = list(
        db.scalars(
            select(MessageSelectionComment)
            .where(
                MessageSelectionComment.message_id == message.id,
                MessageSelectionComment.author_user_id == user.id,
                MessageSelectionComment.deleted_at.is_(None),
            )
            .order_by(MessageSelectionComment.created_at)
        )
    )
    return message, comments


def require_owned_comment(
    db: Session, user: User, comment_id: str
) -> tuple[Message, MessageSelectionComment]:
    comment = db.get(MessageSelectionComment, comment_id)
    if (
        comment is None
        or comment.author_user_id != user.id
        or comment.deleted_at is not None
    ):
        raise ApiProblem(404, "comment_not_found", "Comment를 찾을 수 없습니다.")
    message = require_message(db, user, comment.message_id, assistant_only=True)
    return message, comment


def patch_comment(
    db: Session,
    *,
    user: User,
    comment_id: str,
    instruction: str | None,
    status: str | None,
) -> tuple[Message, MessageSelectionComment]:
    message, comment = require_owned_comment(db, user, comment_id)
    if instruction is not None:
        comment.instruction = instruction
    if status is not None:
        comment.status = status
    comment.updated_at = utc_now()
    append_interaction_event(
        db,
        message,
        "message_comment_changed",
        {"messageId": message.id, "commentId": comment.id, "status": comment.status},
    )
    return message, comment


def delete_comment(
    db: Session, *, user: User, comment_id: str
) -> tuple[Message, MessageSelectionComment]:
    message, comment = require_owned_comment(db, user, comment_id)
    comment.status = "deleted"
    comment.deleted_at = utc_now()
    comment.updated_at = comment.deleted_at
    append_interaction_event(
        db,
        message,
        "message_comment_changed",
        {
            "messageId": message.id,
            "commentId": comment.id,
            "status": "deleted",
        },
    )
    return message, comment


def reference_payload(reference: MessageReference) -> dict[str, Any]:
    return {
        "id": reference.id,
        "messageId": reference.message_id,
        "kind": reference.kind,
        "referenceId": reference.reference_id,
        "versionOrDigest": reference.version_or_digest,
        "tokenStart": None if reference.token_start < 0 else reference.token_start,
        "tokenEnd": reference.token_end,
        "displaySnapshot": reference.display_snapshot_json,
        "validationStatus": reference.validation_status,
    }


def feedback_payload(feedback: MessageFeedback) -> dict[str, Any]:
    return {
        "id": feedback.id,
        "messageId": feedback.message_id,
        "kind": feedback.kind,
        "value": feedback.rating_value,
        "category": feedback.report_category,
        "description": feedback.report_description,
        "diagnosticScope": feedback.diagnostic_scope_json,
        "status": feedback.status,
        "createdAt": feedback.created_at,
        "updatedAt": feedback.updated_at,
    }


def comment_payload(comment: MessageSelectionComment) -> dict[str, Any]:
    return {
        "id": comment.id,
        "messageId": comment.message_id,
        "blockId": comment.block_id,
        "startOffset": comment.start_offset,
        "endOffset": comment.end_offset,
        "selectedText": comment.selected_text,
        "prefixContext": comment.prefix_context,
        "suffixContext": comment.suffix_context,
        "instruction": comment.instruction,
        "anchorStatus": comment.anchor_status,
        "status": comment.status,
        "createdAt": comment.created_at,
        "updatedAt": comment.updated_at,
    }
