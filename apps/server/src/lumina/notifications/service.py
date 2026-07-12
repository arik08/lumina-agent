from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..audit import record_audit
from ..models import (
    Artifact,
    Conversation,
    Notification,
    Run,
    ScheduledRun,
    ScheduledTask,
    User,
    utc_now,
)


_RUN_NOTIFICATION_COPY = {
    "completed": (
        "run_completed",
        "작업이 완료되었습니다.",
        "완료된 작업의 결과를 확인할 수 있습니다.",
    ),
    "failed": (
        "run_failed",
        "작업을 완료하지 못했습니다.",
        "작업 화면에서 실패 상태와 다시 시도할 수 있는 항목을 확인해 주세요.",
    ),
    "limit_reached": (
        "run_limit_reached",
        "실행 한도에 도달했습니다.",
        "작업 화면에서 현재 결과와 실행 한도를 확인해 주세요.",
    ),
    "awaiting_approval": (
        "run_approval_required",
        "작업 승인이 필요합니다.",
        "작업 화면에서 승인 요청의 범위를 확인해 주세요.",
    ),
}
_SCHEDULED_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "interrupted",
    "limit_reached",
}
_DEEP_LINK_KEYS = frozenset(
    {
        "target",
        "projectId",
        "conversationId",
        "runId",
        "artifactId",
        "scheduledTaskId",
        "scheduledRunId",
    }
)


def _clean_deep_link(value: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, item in value.items():
        if key not in _DEEP_LINK_KEYS or not isinstance(item, str):
            continue
        normalized = item.strip()
        if not normalized or len(normalized) > 128:
            continue
        result[key] = normalized
    return result


def _create_notification(
    db: Session,
    *,
    user_id: str,
    kind: str,
    title: str,
    body: str,
    source_type: str,
    source_id: str,
    idempotency_key: str,
    deep_link: dict[str, Any],
    project_id: str | None = None,
    conversation_id: str | None = None,
    run_id: str | None = None,
    scheduled_task_id: str | None = None,
    scheduled_run_id: str | None = None,
) -> tuple[Notification | None, bool]:
    user = db.get(User, user_id)
    if user is None:
        return None, False
    existing = db.scalar(
        select(Notification).where(
            Notification.user_id == user.id,
            Notification.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing, False
    notification = Notification(
        organization_id=user.organization_id,
        user_id=user.id,
        kind=kind,
        title=title,
        body=body,
        source_type=source_type,
        source_id=source_id,
        project_id=project_id,
        conversation_id=conversation_id,
        run_id=run_id,
        scheduled_task_id=scheduled_task_id,
        scheduled_run_id=scheduled_run_id,
        deep_link_json=_clean_deep_link(deep_link),
        idempotency_key=idempotency_key,
    )
    try:
        with db.begin_nested():
            db.add(notification)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(Notification).where(
                Notification.user_id == user.id,
                Notification.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        return existing, False
    record_audit(
        db,
        actor=user,
        action="notification_created",
        target_type="notification",
        target_id=notification.id,
        result="success",
        metadata={
            "kind": kind,
            "source_type": source_type,
            "source_id": source_id,
        },
    )
    return notification, True


def create_run_transition_notification(
    db: Session, run: Run, target: str
) -> tuple[Notification | None, bool]:
    copy = _RUN_NOTIFICATION_COPY.get(target)
    if copy is None:
        return None, False
    scheduled_run_id = run.snapshot_json.get("scheduled_run_id")
    if isinstance(scheduled_run_id, str) and target != "awaiting_approval":
        return None, False
    scheduled_task_id = run.snapshot_json.get("scheduled_task_id")
    artifact_id = db.scalar(
        select(Artifact.id)
        .where(Artifact.source_run_id == run.id, Artifact.deleted_at.is_(None))
        .order_by(Artifact.created_at, Artifact.id)
        .limit(1)
    )
    kind, title, body = copy
    conversation = db.get(Conversation, run.conversation_id)
    if target == "completed":
        conversation_title = conversation.title.strip() if conversation else ""
        title = f"{conversation_title or '작업'} · 완료"
        db.execute(
            delete(Notification).where(
                Notification.user_id == run.user_id,
                Notification.conversation_id == run.conversation_id,
                Notification.kind == "run_completed",
                Notification.run_id != run.id,
            )
        )
    deep_link = {
        "target": "artifact" if artifact_id else "conversation",
        "projectId": run.project_id,
        "conversationId": run.conversation_id,
        "runId": run.id,
        **({"artifactId": artifact_id} if artifact_id else {}),
        **(
            {"scheduledTaskId": scheduled_task_id}
            if isinstance(scheduled_task_id, str)
            else {}
        ),
        **(
            {"scheduledRunId": scheduled_run_id}
            if isinstance(scheduled_run_id, str)
            else {}
        ),
    }
    return _create_notification(
        db,
        user_id=run.user_id,
        kind=kind,
        title=title,
        body=body,
        source_type="run",
        source_id=run.id,
        idempotency_key=f"run:{run.id}:status:{target}",
        deep_link=deep_link,
        project_id=run.project_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        scheduled_task_id=(
            scheduled_task_id if isinstance(scheduled_task_id, str) else None
        ),
        scheduled_run_id=(
            scheduled_run_id if isinstance(scheduled_run_id, str) else None
        ),
    )


def delete_notification(db: Session, *, user: User, notification_id: str) -> Notification:
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    if notification is None:
        raise ApiProblem(404, "notification_not_found", "알림을 찾을 수 없습니다.")
    db.delete(notification)
    return notification


def delete_all_notifications(db: Session, *, user: User) -> int:
    result = db.execute(delete(Notification).where(Notification.user_id == user.id))
    return int(result.rowcount or 0)


def create_scheduled_run_result_notification(
    db: Session, scheduled_run: ScheduledRun
) -> tuple[Notification | None, bool]:
    if scheduled_run.status not in _SCHEDULED_TERMINAL_STATUSES:
        return None, False
    task = db.get(ScheduledTask, scheduled_run.scheduled_task_id)
    run = db.get(Run, scheduled_run.run_id) if scheduled_run.run_id else None
    project_id = (
        task.project_id if task is not None else (run.project_id if run else None)
    )
    raw_conversation_id = scheduled_run.input_snapshot_json.get("conversation_id")
    conversation_id = (
        raw_conversation_id
        if isinstance(raw_conversation_id, str)
        else (task.source_conversation_id if task is not None else None)
    )
    if conversation_id is None and run is not None:
        conversation_id = run.conversation_id
    artifact_id = next(
        (
            item
            for item in scheduled_run.output_artifact_ids_json
            if isinstance(item, str) and item
        ),
        None,
    )
    completed = scheduled_run.status == "completed"
    return _create_notification(
        db,
        user_id=scheduled_run.requested_by_user_id,
        kind=("scheduled_run_completed" if completed else "scheduled_run_failed"),
        title=(
            "예약 작업이 완료되었습니다."
            if completed
            else "예약 작업을 완료하지 못했습니다."
        ),
        body=(
            "예약 작업의 결과를 확인할 수 있습니다."
            if completed
            else "예약 작업 화면에서 실행 상태와 재시도 여부를 확인해 주세요."
        ),
        source_type="scheduled_run",
        source_id=scheduled_run.id,
        idempotency_key=f"scheduled-run:{scheduled_run.id}:result",
        deep_link={
            "target": "artifact" if artifact_id else "conversation",
            **({"projectId": project_id} if project_id else {}),
            **({"conversationId": conversation_id} if conversation_id else {}),
            **({"runId": scheduled_run.run_id} if scheduled_run.run_id else {}),
            **({"artifactId": artifact_id} if artifact_id else {}),
            "scheduledTaskId": scheduled_run.scheduled_task_id,
            "scheduledRunId": scheduled_run.id,
        },
        project_id=project_id,
        conversation_id=conversation_id,
        run_id=scheduled_run.run_id,
        scheduled_task_id=scheduled_run.scheduled_task_id,
        scheduled_run_id=scheduled_run.id,
    )


def list_notifications(
    db: Session,
    *,
    user: User,
    unread_only: bool,
    limit: int,
    offset: int,
) -> tuple[list[Notification], bool]:
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    rows = list(
        db.scalars(
            query.order_by(Notification.created_at.desc(), Notification.id.desc())
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return rows[:limit], len(rows) > limit


def unread_notification_count(db: Session, *, user: User) -> int:
    return int(
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id,
                Notification.read_at.is_(None),
            )
        )
        or 0
    )


def mark_notification_read(
    db: Session, *, user: User, notification_id: str
) -> tuple[Notification, bool]:
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    if notification is None:
        raise ApiProblem(404, "notification_not_found", "알림을 찾을 수 없습니다.")
    if notification.read_at is not None:
        return notification, False
    notification.read_at = utc_now()
    db.flush()
    return notification, True


def mark_all_notifications_read(db: Session, *, user: User) -> tuple[int, datetime]:
    read_at = utc_now()
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=read_at)
    )
    return int(getattr(result, "rowcount", 0)), read_at


def notification_payload(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "kind": notification.kind,
        "title": notification.title,
        "body": notification.body,
        "deepLink": notification.deep_link_json,
        "readAt": notification.read_at,
        "createdAt": notification.created_at,
    }
