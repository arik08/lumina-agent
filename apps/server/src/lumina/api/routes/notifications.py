from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...db import get_db
from ...models import User
from ...notifications import (
    delete_all_notifications,
    delete_notification,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    notification_payload,
    unread_notification_count,
)
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..schemas import (
    NotificationListResponse,
    NotificationReadAllResponse,
    NotificationResponse,
    NotificationUnreadCountResponse,
)


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.delete("", status_code=204)
def delete_all(
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    deleted_count = delete_all_notifications(db, user=context.user)
    record_audit(
        db,
        actor=context.user,
        action="notifications_deleted_all",
        target_type="notification",
        result="success",
        request_id=getattr(request.state, "request_id", None),
        metadata={"deleted_count": deleted_count},
    )
    db.commit()
    return Response(status_code=204)


@router.get("/unread-count", response_model=NotificationUnreadCountResponse)
def get_unread_count(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    return {"unreadCount": unread_notification_count(db, user=user)}


@router.post("/read-all", response_model=NotificationReadAllResponse)
def post_read_all(
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    updated_count, read_at = mark_all_notifications_read(db, user=context.user)
    record_audit(
        db,
        actor=context.user,
        action="notifications_read_all",
        target_type="notification",
        result="success",
        request_id=getattr(request.state, "request_id", None),
        metadata={"updated_count": updated_count},
    )
    db.commit()
    return {"updatedCount": updated_count, "readAt": read_at}


@router.get("", response_model=NotificationListResponse)
def get_notifications(
    unread_only: bool = Query(default=False, alias="unreadOnly"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    rows, has_more = list_notifications(
        db,
        user=user,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [notification_payload(row) for row in rows],
        "unreadCount": unread_notification_count(db, user=user),
        "nextOffset": offset + limit if has_more else None,
        "hasMore": has_more,
    }


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def post_read(
    notification_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    notification, changed = mark_notification_read(
        db,
        user=context.user,
        notification_id=notification_id,
    )
    if changed:
        record_audit(
            db,
            actor=context.user,
            action="notification_read",
            target_type="notification",
            target_id=notification.id,
            result="success",
            request_id=getattr(request.state, "request_id", None),
            metadata={"kind": notification.kind},
        )
    db.commit()
    return notification_payload(notification)


@router.delete("/{notification_id}", status_code=204)
def delete_one(
    notification_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    notification = delete_notification(
        db,
        user=context.user,
        notification_id=notification_id,
    )
    record_audit(
        db,
        actor=context.user,
        action="notification_deleted",
        target_type="notification",
        target_id=notification.id,
        result="success",
        request_id=getattr(request.state, "request_id", None),
        metadata={"kind": notification.kind},
    )
    db.commit()
    return Response(status_code=204)
