from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...db import get_db
from ...models import Announcement, AnnouncementReceipt, User, utc_now
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
from ..errors import ApiProblem
from ..schemas import (
    AnnouncementListResponse,
    AnnouncementResponse,
    NotificationListResponse,
    NotificationReadAllResponse,
    NotificationResponse,
    NotificationUnreadCountResponse,
)


router = APIRouter(prefix="/notifications", tags=["notifications"])


def _announcement_payload(
    db: Session,
    announcement: Announcement,
    *,
    read_at: datetime | None = None,
) -> dict[str, object]:
    author = db.get(User, announcement.creator_user_id) if announcement.creator_user_id else None
    return {
        "id": announcement.id,
        "title": announcement.title,
        "body": announcement.body,
        "author": {
            "id": author.id,
            "loginId": author.login_id,
            "displayName": author.display_name,
        }
        if author is not None
        else None,
        "readAt": read_at,
        "createdAt": announcement.created_at,
        "updatedAt": announcement.updated_at,
    }


def _announcement_unread_filter(user: User):
    return ~select(AnnouncementReceipt.id).where(
        AnnouncementReceipt.announcement_id == Announcement.id,
        AnnouncementReceipt.user_id == user.id,
        AnnouncementReceipt.read_at >= Announcement.updated_at,
    ).exists()


def _announcement_unread_count(db: Session, user: User) -> int:
    return int(
        db.scalar(
            select(func.count(Announcement.id)).where(
                Announcement.organization_id == user.organization_id,
                _announcement_unread_filter(user),
            )
        )
        or 0
    )


@router.get(
    "/announcements/unread-count",
    response_model=NotificationUnreadCountResponse,
)
def get_announcement_unread_count(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    return {"unreadCount": _announcement_unread_count(db, user)}


@router.get("/announcements", response_model=AnnouncementListResponse)
def get_announcements(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    filters = [Announcement.organization_id == user.organization_id]
    total = int(db.scalar(select(func.count(Announcement.id)).where(*filters)) or 0)
    rows = list(
        db.scalars(
            select(Announcement)
            .where(*filters)
            .order_by(Announcement.created_at.desc(), Announcement.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    announcement_ids = [row.id for row in rows]
    receipts = {
        receipt.announcement_id: receipt.read_at
        for receipt in db.scalars(
            select(AnnouncementReceipt).where(
                AnnouncementReceipt.user_id == user.id,
                AnnouncementReceipt.announcement_id.in_(announcement_ids),
            )
        )
    } if announcement_ids else {}
    items = [
        _announcement_payload(
            db,
            row,
            read_at=(
                receipts.get(row.id)
                if receipts.get(row.id) is not None
                and receipts[row.id] >= row.updated_at
                else None
            ),
        )
        for row in rows
    ]
    return {
        "items": items,
        "total": total,
        "unreadCount": _announcement_unread_count(db, user),
    }


@router.post(
    "/announcements/{announcement_id}/read",
    response_model=AnnouncementResponse,
)
def post_announcement_read(
    announcement_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    announcement = db.scalar(
        select(Announcement).where(
            Announcement.id == announcement_id,
            Announcement.organization_id == context.user.organization_id,
        )
    )
    if announcement is None:
        raise ApiProblem(404, "announcement_not_found", "공지사항을 찾을 수 없습니다.")
    receipt = db.scalar(
        select(AnnouncementReceipt).where(
            AnnouncementReceipt.announcement_id == announcement.id,
            AnnouncementReceipt.user_id == context.user.id,
        )
    )
    read_at = utc_now()
    if receipt is None:
        receipt = AnnouncementReceipt(
            announcement_id=announcement.id,
            user_id=context.user.id,
            read_at=read_at,
        )
        db.add(receipt)
    else:
        receipt.read_at = read_at
    record_audit(
        db,
        actor=context.user,
        action="announcement_read",
        target_type="announcement",
        target_id=announcement.id,
        result="success",
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return _announcement_payload(db, announcement, read_at=read_at)


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
