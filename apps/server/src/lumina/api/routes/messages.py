from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...db import get_db
from ...messages.schemas import CommentCreate, CommentPatch, RatingPut, ReportCreate
from ...messages.service import (
    comment_payload,
    create_comment,
    create_report,
    delete_comment,
    delete_rating,
    feedback_payload,
    list_comments,
    list_feedback,
    patch_comment,
    put_rating,
    reference_payload,
    synchronize_message_references,
)
from ...models import User
from ..dependencies import AuthContext, get_current_user, require_csrf


router = APIRouter(tags=["message-interactions"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/messages/{message_id}/references")
def get_message_references(
    message_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = synchronize_message_references(db, user=user, message_id=message_id)
    db.commit()
    return [reference_payload(item) for item in rows]


@router.get("/messages/{message_id}/feedback")
def get_message_feedback(
    message_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _message, rows = list_feedback(db, user=user, message_id=message_id)
    return [feedback_payload(item) for item in rows]


@router.put("/messages/{message_id}/rating")
def put_message_rating(
    message_id: str,
    payload: RatingPut,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    message, rating = put_rating(
        db,
        user=context.user,
        message_id=message_id,
        value=payload.value,
    )
    record_audit(
        db,
        action="message_rating_changed",
        target_type="message",
        target_id=message.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"value": rating.rating_value},
    )
    db.commit()
    return feedback_payload(rating)


@router.delete("/messages/{message_id}/rating", status_code=204)
def delete_message_rating(
    message_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    message, _rating = delete_rating(db, user=context.user, message_id=message_id)
    record_audit(
        db,
        action="message_rating_deleted",
        target_type="message",
        target_id=message.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return Response(status_code=204)


@router.post("/messages/{message_id}/reports", status_code=201)
def post_message_report(
    message_id: str,
    payload: ReportCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    message, report = create_report(
        db,
        user=context.user,
        message_id=message_id,
        category=payload.category,
        description=payload.description,
        diagnostic_scope=payload.diagnostic_scope.model_dump(by_alias=True),
    )
    record_audit(
        db,
        action="message_report_created",
        target_type="message_feedback",
        target_id=report.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "message_id": message.id,
            "category": report.report_category,
            "diagnostic_scope": report.diagnostic_scope_json,
        },
    )
    db.commit()
    return feedback_payload(report)


@router.get("/messages/{message_id}/comments")
def get_message_comments(
    message_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _message, rows = list_comments(db, user=user, message_id=message_id)
    return [comment_payload(item) for item in rows]


@router.post("/messages/{message_id}/comments", status_code=201)
def post_message_comment(
    message_id: str,
    payload: CommentCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    message, comment = create_comment(
        db,
        user=context.user,
        message_id=message_id,
        block_id=payload.block_id,
        start_offset=payload.start_offset,
        end_offset=payload.end_offset,
        selected_text=payload.selected_text,
        prefix_context=payload.prefix_context,
        suffix_context=payload.suffix_context,
        instruction=payload.instruction,
        status=payload.status,
    )
    record_audit(
        db,
        action="message_comment_created",
        target_type="message_selection_comment",
        target_id=comment.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "message_id": message.id,
            "anchor_status": comment.anchor_status,
        },
    )
    db.commit()
    return comment_payload(comment)


@router.patch("/message-comments/{comment_id}")
def patch_message_comment(
    comment_id: str,
    payload: CommentPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _message, comment = patch_comment(
        db,
        user=context.user,
        comment_id=comment_id,
        instruction=payload.instruction,
        status=payload.status,
    )
    record_audit(
        db,
        action="message_comment_changed",
        target_type="message_selection_comment",
        target_id=comment.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"status": comment.status},
    )
    db.commit()
    return comment_payload(comment)


@router.delete("/message-comments/{comment_id}", status_code=204)
def delete_message_comment(
    comment_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    _message, comment = delete_comment(db, user=context.user, comment_id=comment_id)
    record_audit(
        db,
        action="message_comment_deleted",
        target_type="message_selection_comment",
        target_id=comment.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return Response(status_code=204)
