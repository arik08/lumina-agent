from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Literal, get_args
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...agent.executor import local_run_executor
from ...auth import create_user, revoke_user_sessions
from ...auth.security import hash_password
from ...authorization import require_admin
from ...config import Settings, get_settings
from ...db import get_db
from ...models import (
    Announcement,
    Artifact,
    AuthSession,
    AuditEvent,
    Conversation,
    ConversationShareGrant,
    Message,
    MessageFeedback,
    Organization,
    Run,
    User,
    utc_now,
)
from ...runs.broker import event_broker
from ...runs.safety import normalize_run_safety_settings, run_safety_payload
from ...runs.service import cancel_organization_work, message_response, run_snapshot
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem
from ..schemas import AnnouncementListResponse, AnnouncementResponse, ApiModel


router = APIRouter(prefix="/admin", tags=["admin"])

UserStatus = Literal["invited", "active", "locked", "disabled"]
UserRole = Literal["user", "admin"]
_USER_STATUSES = frozenset(get_args(UserStatus))
_USER_ROLES = frozenset(get_args(UserRole))
_LAUNCHER_EVENT_TYPES = frozenset({"automatic_recovery", "manual_restart"})
_ANALYTICS_TIMEZONE = ZoneInfo("Asia/Seoul")


class AdminUserCreate(ApiModel):
    login_name: str = Field(min_length=1, max_length=120)
    login_domain: str = Field(default="posco.com", min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)
    display_name: str | None = Field(default=None, max_length=200)
    affiliation: str | None = Field(default=None, max_length=200)
    role: UserRole = "user"
    status: UserStatus = "active"
    must_change_password: bool = False


class AdminUserPatch(ApiModel):
    display_name: str | None = Field(default=None, max_length=200)
    affiliation: str | None = Field(default=None, max_length=200)
    role: UserRole | None = None
    status: UserStatus | None = None


class AdminPasswordReset(ApiModel):
    new_password: str = Field(min_length=1, max_length=1024)
    must_change_password: bool = False


class AdminShareRevoke(ApiModel):
    reason: str = Field(default="", max_length=1000)


class AdminRunSafetyPatch(ApiModel):
    max_model_turns: int = Field(ge=10, le=10_000)
    max_total_tokens: int = Field(ge=100_000, le=100_000_000)
    max_elapsed_minutes: int = Field(ge=30, le=525_600)
    max_cost_usd: float = Field(ge=1, le=10_000)


class AdminEmergencyStop(ApiModel):
    reason: str = Field(default="관리자 비상 중단", max_length=1000)


class AdminAnnouncementCreate(ApiModel):
    title: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1, max_length=20_000)


class AdminAnnouncementPatch(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    body: str | None = Field(default=None, min_length=1, max_length=20_000)

    @model_validator(mode="after")
    def require_change(self) -> "AdminAnnouncementPatch":
        if self.title is None and self.body is None:
            raise ValueError("title or body is required")
        return self


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _announcement_payload(db: Session, announcement: Announcement) -> dict[str, object]:
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
        "createdAt": announcement.created_at,
        "updatedAt": announcement.updated_at,
    }


def _require_announcement(db: Session, actor: User, announcement_id: str) -> Announcement:
    require_admin(actor)
    announcement = db.scalar(
        select(Announcement).where(
            Announcement.id == announcement_id,
            Announcement.organization_id == actor.organization_id,
        )
    )
    if announcement is None:
        raise ApiProblem(404, "announcement_not_found", "공지사항을 찾을 수 없습니다.")
    return announcement


@router.get("/announcements", response_model=AnnouncementListResponse)
def list_announcements(
    request: Request,
    query: str = "",
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(actor)
    filters = [Announcement.organization_id == actor.organization_id]
    normalized_query = query.strip().casefold()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        filters.append(
            or_(
                func.lower(Announcement.title).like(pattern),
                func.lower(Announcement.body).like(pattern),
            )
        )
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
    record_audit(
        db,
        actor=actor,
        action="admin_announcement_list_viewed",
        target_type="announcement",
        result="success",
        request_id=_request_id(request),
        metadata={"query": query, "limit": limit, "offset": offset},
    )
    db.commit()
    return {"items": [_announcement_payload(db, row) for row in rows], "total": total}


@router.post("/announcements", response_model=AnnouncementResponse, status_code=201)
def create_announcement(
    payload: AdminAnnouncementCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(context.user)
    announcement = Announcement(
        organization_id=context.user.organization_id,
        creator_user_id=context.user.id,
        title=payload.title.strip(),
        body=payload.body.strip(),
    )
    if not announcement.title or not announcement.body:
        raise ApiProblem(422, "invalid_announcement", "제목과 내용을 입력해 주세요.")
    db.add(announcement)
    db.flush()
    record_audit(
        db,
        actor=context.user,
        action="announcement_created",
        target_type="announcement",
        target_id=announcement.id,
        result="success",
        request_id=_request_id(request),
        metadata={"title": announcement.title},
    )
    db.commit()
    db.refresh(announcement)
    return _announcement_payload(db, announcement)


@router.patch("/announcements/{announcement_id}", response_model=AnnouncementResponse)
def update_announcement(
    announcement_id: str,
    payload: AdminAnnouncementPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    announcement = _require_announcement(db, context.user, announcement_id)
    if payload.title is not None:
        announcement.title = payload.title.strip()
    if payload.body is not None:
        announcement.body = payload.body.strip()
    if not announcement.title or not announcement.body:
        raise ApiProblem(422, "invalid_announcement", "제목과 내용을 입력해 주세요.")
    announcement.updated_at = utc_now()
    record_audit(
        db,
        actor=context.user,
        action="announcement_updated",
        target_type="announcement",
        target_id=announcement.id,
        result="success",
        request_id=_request_id(request),
        metadata={"title": announcement.title},
    )
    db.commit()
    db.refresh(announcement)
    return _announcement_payload(db, announcement)


@router.delete("/announcements/{announcement_id}", status_code=204)
def delete_announcement(
    announcement_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    announcement = _require_announcement(db, context.user, announcement_id)
    record_audit(
        db,
        actor=context.user,
        action="announcement_deleted",
        target_type="announcement",
        target_id=announcement.id,
        result="success",
        request_id=_request_id(request),
        metadata={"title": announcement.title},
    )
    db.delete(announcement)
    db.commit()
    return Response(status_code=204)


def _launcher_monitoring_events(
    path: Path, *, window_start: datetime, window_end: datetime
) -> list[tuple[datetime, str]]:
    events: list[tuple[datetime, str]] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return events
    for line in lines:
        try:
            payload = json.loads(line)
            event = payload.get("event")
            timestamp = datetime.fromisoformat(str(payload.get("timestamp", "")))
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if event not in _LAUNCHER_EVENT_TYPES or timestamp.tzinfo is None:
            continue
        timestamp = timestamp.astimezone(UTC)
        if window_start <= timestamp < window_end:
            events.append((timestamp, event))
    return events


def _user_payload(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "loginId": user.login_id,
        "loginName": user.login_name,
        "loginDomain": user.login_domain,
        "displayName": user.display_name,
        "affiliation": user.affiliation,
        "role": user.role,
        "status": user.status,
        "mustChangePassword": user.must_change_password,
        "failedLoginCount": user.failed_login_count,
        "lockedUntil": user.locked_until,
        "lastLoginAt": user.last_login_at,
        "createdAt": user.created_at,
        "updatedAt": user.updated_at,
    }


def _require_admin_user(db: Session, actor: User, user_id: str) -> User:
    require_admin(actor)
    user = db.scalar(
        select(User).where(
            User.id == user_id,
            User.organization_id == actor.organization_id,
        )
    )
    if user is None:
        raise ApiProblem(404, "not_found", "사용자를 찾을 수 없습니다.")
    return user


def _other_active_admin_count(db: Session, actor: User, target: User) -> int:
    return int(
        db.scalar(
            select(func.count(User.id)).where(
                User.organization_id == actor.organization_id,
                User.role == "admin",
                User.status == "active",
                User.id != target.id,
            )
        )
        or 0
    )


def _guard_last_active_admin(
    db: Session,
    actor: User,
    target: User,
    *,
    new_role: str | None = None,
    new_status: str | None = None,
) -> None:
    effective_role = new_role or target.role
    effective_status = new_status or target.status
    removes_active_admin = (
        target.role == "admin"
        and target.status == "active"
        and (effective_role != "admin" or effective_status != "active")
    )
    if removes_active_admin and _other_active_admin_count(db, actor, target) == 0:
        raise ApiProblem(
            409,
            "last_active_admin",
            "마지막 활성 관리자 계정은 비활성화하거나 강등할 수 없습니다.",
        )


def _usage_number(usage: dict[str, object], key: str) -> float:
    value = usage.get(key, 0)
    return (
        float(value)
        if isinstance(value, int | float) and not isinstance(value, bool)
        else 0.0
    )


@router.get("/usage-statistics")
def get_usage_statistics(
    request: Request,
    days: int = Query(default=30, ge=0, le=90),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Return organization-level activity derived from login sessions and agent runs."""
    require_admin(actor)
    now = utc_now()
    today = now.astimezone(_ANALYTICS_TIMEZONE).date()
    month_start = datetime.combine(
        today - timedelta(days=29), time.min, _ANALYTICS_TIMEZONE
    ).astimezone(UTC)

    users = list(
        db.scalars(
            select(User)
            .where(User.organization_id == actor.organization_id)
            .order_by(User.login_id)
        )
    )
    session_query = (
        select(AuthSession)
        .join(User, User.id == AuthSession.user_id)
        .where(User.organization_id == actor.organization_id)
    )
    run_query = select(Run).where(Run.organization_id == actor.organization_id)
    if days:
        requested_first_day = today - timedelta(days=days - 1)
        range_start = datetime.combine(
            requested_first_day, time.min, _ANALYTICS_TIMEZONE
        ).astimezone(UTC)
        session_query = session_query.where(AuthSession.created_at >= range_start)
        run_query = run_query.where(Run.created_at >= range_start)
    sessions = list(db.scalars(session_query))
    runs = list(db.scalars(run_query))

    if days:
        first_day = today - timedelta(days=days - 1)
    else:
        activity_dates = [
            session.created_at.astimezone(_ANALYTICS_TIMEZONE).date()
            for session in sessions
        ] + [
            run.created_at.astimezone(_ANALYTICS_TIMEZONE).date() for run in runs
        ]
        first_day = min(activity_dates, default=today)
    period_days = (today - first_day).days + 1

    dates = [first_day + timedelta(days=index) for index in range(period_days)]
    daily_users: dict[date, set[str]] = {day: set() for day in dates}
    daily_logins = {day: 0 for day in dates}
    daily_runs = {day: 0 for day in dates}
    user_activity: dict[str, set[date]] = {user.id: set() for user in users}
    user_logins = {user.id: 0 for user in users}
    user_runs = {user.id: 0 for user in users}
    user_input_tokens = {user.id: 0 for user in users}
    user_cached_input_tokens = {user.id: 0 for user in users}
    user_uncached_input_tokens = {user.id: 0 for user in users}
    user_output_tokens = {user.id: 0 for user in users}
    user_cost = {user.id: 0.0 for user in users}

    for session in sessions:
        day = session.created_at.astimezone(_ANALYTICS_TIMEZONE).date()
        if day in daily_users:
            daily_users[day].add(session.user_id)
            daily_logins[day] += 1
            user_activity.setdefault(session.user_id, set()).add(day)
            user_logins[session.user_id] = user_logins.get(session.user_id, 0) + 1

    for run in runs:
        day = run.created_at.astimezone(_ANALYTICS_TIMEZONE).date()
        if day in daily_users:
            daily_users[day].add(run.user_id)
            daily_runs[day] += 1
            user_activity.setdefault(run.user_id, set()).add(day)
            user_runs[run.user_id] = user_runs.get(run.user_id, 0) + 1
            usage = run.usage_json or {}
            input_tokens = int(_usage_number(usage, "input_tokens"))
            cached_input_tokens = int(_usage_number(usage, "cached_input_tokens"))
            uncached_input_tokens = int(_usage_number(usage, "uncached_input_tokens"))
            if "uncached_input_tokens" not in usage:
                uncached_input_tokens = max(0, input_tokens - cached_input_tokens)
            user_input_tokens[run.user_id] = (
                user_input_tokens.get(run.user_id, 0) + input_tokens
            )
            user_cached_input_tokens[run.user_id] = (
                user_cached_input_tokens.get(run.user_id, 0) + cached_input_tokens
            )
            user_uncached_input_tokens[run.user_id] = (
                user_uncached_input_tokens.get(run.user_id, 0) + uncached_input_tokens
            )
            user_output_tokens[run.user_id] = user_output_tokens.get(
                run.user_id, 0
            ) + int(_usage_number(usage, "output_tokens"))
            user_cost[run.user_id] = user_cost.get(run.user_id, 0.0) + _usage_number(
                usage, "cost_usd"
            )

    dau = len(daily_users[today])
    wau_users = set().union(
        *(daily_users[day] for day in dates if day >= today - timedelta(days=6))
    )
    mau_users = set().union(
        *(daily_users[day] for day in dates if day >= today - timedelta(days=29))
    )
    new_users = sum(1 for user in users if user.created_at >= month_start)
    per_user_rows: list[tuple[tuple[int, int, str], dict[str, object]]] = []
    for user in users:
        active_days = user_activity.get(user.id, set())
        last_active_day = max(active_days) if active_days else None
        cached_input_tokens = user_cached_input_tokens.get(user.id, 0)
        uncached_input_tokens = user_uncached_input_tokens.get(user.id, 0)
        cacheable_input_tokens = cached_input_tokens + uncached_input_tokens
        run_count = user_runs.get(user.id, 0)
        row: dict[str, object] = {
            "userId": user.id,
            "loginId": user.login_id,
            "displayName": user.display_name,
            "affiliation": user.affiliation,
            "status": user.status,
            "lastLoginAt": user.last_login_at,
            "activeDays": len(active_days),
            "loginCount": user_logins.get(user.id, 0),
            "runCount": run_count,
            "inputTokens": user_input_tokens.get(user.id, 0),
            "cachedInputTokens": cached_input_tokens,
            "cacheHitRatioPercent": round(
                cached_input_tokens / cacheable_input_tokens * 100, 1
            )
            if cacheable_input_tokens
            else 0,
            "outputTokens": user_output_tokens.get(user.id, 0),
            "estimatedCostUsd": round(user_cost.get(user.id, 0.0), 6),
            "lastActiveDate": last_active_day.isoformat()
            if last_active_day
            else None,
            "inactiveDays": (today - last_active_day).days
            if last_active_day
            else None,
        }
        per_user_rows.append(
            ((len(active_days), run_count, user.login_id), row)
        )
    per_user_rows.sort(key=lambda item: item[0], reverse=True)
    per_user = [row for _sort_key, row in per_user_rows]

    record_audit(
        db,
        action="admin_usage_statistics_viewed",
        target_type="usage_statistics",
        result="success",
        actor=actor,
        request_id=_request_id(request),
        metadata={"days": days},
    )
    db.commit()
    return {
        "generatedAt": now,
        "timezone": str(_ANALYTICS_TIMEZONE),
        "periodDays": period_days,
        "summary": {
            "dau": dau,
            "wau": len(wau_users),
            "mau": len(mau_users),
            "stickinessPercent": round(dau / len(mau_users) * 100, 1)
            if mau_users
            else 0,
            "newUsers30d": new_users,
            "runs": len(runs),
        },
        "trend": [
            {
                "date": day.isoformat(),
                "activeUsers": len(daily_users[day]),
                "loginCount": daily_logins[day],
                "runCount": daily_runs[day],
            }
            for day in dates
        ],
        "users": per_user,
    }


@router.get("/users")
def list_users(
    request: Request,
    query: str = "",
    role: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(actor)
    if role is not None and role not in _USER_ROLES:
        raise ApiProblem(400, "invalid_role", "지원하지 않는 role입니다.")
    if status is not None and status not in _USER_STATUSES:
        raise ApiProblem(400, "invalid_status", "지원하지 않는 계정 상태입니다.")

    filters = [User.organization_id == actor.organization_id]
    normalized_query = query.strip().casefold()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        filters.append(
            or_(
                func.lower(User.login_id).like(pattern),
                func.lower(func.coalesce(User.display_name, "")).like(pattern),
            )
        )
    if role is not None:
        filters.append(User.role == role)
    if status is not None:
        filters.append(User.status == status)

    total = int(db.scalar(select(func.count(User.id)).where(*filters)) or 0)
    users = list(
        db.scalars(
            select(User)
            .where(*filters)
            .order_by(User.created_at.desc(), User.id)
            .offset(offset)
            .limit(limit)
        )
    )
    record_audit(
        db,
        action="admin_user_list_viewed",
        target_type="user",
        result="success",
        actor=actor,
        request_id=_request_id(request),
        metadata={
            "query_used": bool(normalized_query),
            "offset": offset,
            "limit": limit,
        },
    )
    db.commit()
    return {
        "items": [_user_payload(user) for user in users],
        "total": total,
        "offset": offset,
        "hasMore": offset + len(users) < total,
    }


@router.get("/users/{user_id}")
def get_user(
    user_id: str,
    request: Request,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user = _require_admin_user(db, actor, user_id)
    record_audit(
        db,
        action="admin_user_viewed",
        target_type="user",
        target_id=user.id,
        result="success",
        actor=actor,
        request_id=_request_id(request),
    )
    db.commit()
    return _user_payload(user)


@router.post("/users", status_code=201)
def post_user(
    payload: AdminUserCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(context.user)
    try:
        user = create_user(
            db,
            login_name=payload.login_name,
            login_domain=payload.login_domain,
            password=payload.password,
            organization_id=context.user.organization_id,
            display_name=payload.display_name,
            affiliation=payload.affiliation,
            role=payload.role,
            status=payload.status,
            must_change_password=payload.must_change_password,
            created_by_user_id=context.user.id,
        )
    except ValueError as exc:
        message = str(exc)
        code = "login_id_exists" if "already exists" in message else "invalid_user"
        raise ApiProblem(
            409 if code == "login_id_exists" else 400,
            code,
            "사용자를 생성할 수 없습니다.",
        ) from exc

    # create_user records the durable user_created event. Attach this request id
    # without creating a duplicate audit row.
    audit = db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.action == "user_created",
            AuditEvent.target_type == "user",
            AuditEvent.target_id == user.id,
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    if audit is not None:
        audit.request_id = _request_id(request)
    db.commit()
    return _user_payload(user)


@router.patch("/users/{user_id}")
def patch_user(
    user_id: str,
    payload: AdminUserPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    actor = context.user
    user = _require_admin_user(db, actor, user_id)
    _guard_last_active_admin(
        db,
        actor,
        user,
        new_role=payload.role,
        new_status=payload.status,
    )

    changes: dict[str, object] = {}
    if "display_name" in payload.model_fields_set:
        changes["display_name"] = {
            "from": user.display_name,
            "to": payload.display_name,
        }
        user.display_name = payload.display_name
    if "affiliation" in payload.model_fields_set:
        changes["affiliation"] = {
            "from": user.affiliation,
            "to": payload.affiliation,
        }
        user.affiliation = payload.affiliation
    if payload.role is not None and payload.role != user.role:
        changes["role"] = {"from": user.role, "to": payload.role}
        user.role = payload.role
        record_audit(
            db,
            action="role_changed",
            target_type="user",
            target_id=user.id,
            result="success",
            actor=actor,
            request_id=_request_id(request),
            metadata={"new_role": payload.role},
        )
    if payload.status is not None and payload.status != user.status:
        previous_status = user.status
        user.status = payload.status
        user.failed_login_count = 0
        user.locked_until = None
        changes["status"] = {"from": previous_status, "to": payload.status}
        action = {
            "active": "user_unlocked"
            if previous_status == "locked"
            else "user_enabled",
            "locked": "user_locked",
            "disabled": "user_disabled",
            "invited": "user_invited",
        }[payload.status]
        record_audit(
            db,
            action=action,
            target_type="user",
            target_id=user.id,
            result="success",
            actor=actor,
            request_id=_request_id(request),
        )
        if payload.status != "active":
            revoke_user_sessions(db, user.id)
    if not changes:
        raise ApiProblem(400, "no_changes", "변경할 사용자 정보가 없습니다.")

    db.commit()
    return _user_payload(user)


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: str,
    payload: AdminPasswordReset,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    actor = context.user
    user = _require_admin_user(db, actor, user_id)
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = payload.must_change_password
    user.failed_login_count = 0
    user.locked_until = None
    revoked_sessions = revoke_user_sessions(db, user.id)
    record_audit(
        db,
        action="password_reset_issued",
        target_type="user",
        target_id=user.id,
        result="success",
        actor=actor,
        request_id=_request_id(request),
        metadata={
            "must_change_password": payload.must_change_password,
            "revoked_sessions": revoked_sessions,
        },
    )
    db.commit()
    return {
        "user": _user_payload(user),
        "revokedSessionCount": revoked_sessions,
    }


def _conversation_list_payload(
    conversation: Conversation,
    owner: User,
    *,
    run_count: int,
    artifact_count: int,
    share_count: int,
    feedback_count: int,
) -> dict[str, object]:
    return {
        "id": conversation.id,
        "owner": {
            "id": owner.id,
            "loginId": owner.login_id,
            "displayName": owner.display_name,
        },
        "projectId": conversation.project_id,
        "title": conversation.title,
        "status": conversation.status,
        "visibility": conversation.visibility,
        "runCount": run_count,
        "artifactCount": artifact_count,
        "shareCount": share_count,
        "feedbackCount": feedback_count,
        "lastActivityAt": conversation.last_activity_at,
        "createdAt": conversation.created_at,
        "updatedAt": conversation.updated_at,
    }


@router.get("/conversations")
def list_admin_conversations(
    request: Request,
    query: str = "",
    owner_login_id: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
    feedback_only: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(actor)
    filters = [
        Conversation.organization_id == actor.organization_id,
        Conversation.deleted_at.is_(None),
    ]
    normalized_query = query.strip().casefold()
    if normalized_query:
        filters.append(func.lower(Conversation.title).like(f"%{normalized_query}%"))
    if owner_login_id:
        filters.append(func.lower(User.login_id) == owner_login_id.strip().casefold())
    if project_id:
        filters.append(Conversation.project_id == project_id)
    if status:
        filters.append(Conversation.status == status)
    if feedback_only:
        filters.append(
            select(MessageFeedback.id)
            .join(Message, Message.id == MessageFeedback.message_id)
            .where(
                Message.conversation_id == Conversation.id,
                MessageFeedback.deleted_at.is_(None),
            )
            .exists()
        )

    base = (
        select(Conversation, User)
        .join(User, User.id == Conversation.owner_user_id)
        .where(*filters)
    )
    total = int(
        db.scalar(
            select(func.count(Conversation.id))
            .join(User, User.id == Conversation.owner_user_id)
            .where(*filters)
        )
        or 0
    )
    rows = list(
        db.execute(
            base.order_by(Conversation.last_activity_at.desc(), Conversation.id)
            .offset(offset)
            .limit(limit)
        ).all()
    )
    items: list[dict[str, object]] = []
    for conversation, owner in rows:
        run_count = int(
            db.scalar(
                select(func.count(Run.id)).where(Run.conversation_id == conversation.id)
            )
            or 0
        )
        artifact_count = int(
            db.scalar(
                select(func.count(Artifact.id)).where(
                    Artifact.conversation_id == conversation.id,
                    Artifact.deleted_at.is_(None),
                )
            )
            or 0
        )
        share_count = int(
            db.scalar(
                select(func.count(ConversationShareGrant.id)).where(
                    ConversationShareGrant.conversation_id == conversation.id,
                    ConversationShareGrant.revoked_at.is_(None),
                )
            )
            or 0
        )
        feedback_count = int(
            db.scalar(
                select(func.count(MessageFeedback.id))
                .join(Message, Message.id == MessageFeedback.message_id)
                .where(
                    Message.conversation_id == conversation.id,
                    MessageFeedback.deleted_at.is_(None),
                )
            )
            or 0
        )
        items.append(
            _conversation_list_payload(
                conversation,
                owner,
                run_count=run_count,
                artifact_count=artifact_count,
                share_count=share_count,
                feedback_count=feedback_count,
            )
        )

    record_audit(
        db,
        action="admin_conversation_list_viewed",
        target_type="conversation",
        result="success",
        actor=actor,
        request_id=_request_id(request),
        metadata={
            "query_used": bool(normalized_query),
            "feedback_only": feedback_only,
            "offset": offset,
            "limit": limit,
        },
    )
    db.commit()
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "hasMore": offset + len(items) < total,
    }


def _require_admin_conversation(
    db: Session, actor: User, conversation_id: str
) -> Conversation:
    require_admin(actor)
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.organization_id == actor.organization_id,
            Conversation.deleted_at.is_(None),
        )
    )
    if conversation is None:
        raise ApiProblem(404, "not_found", "대화를 찾을 수 없습니다.")
    return conversation


@router.get("/conversations/{conversation_id}")
def get_admin_conversation(
    conversation_id: str,
    request: Request,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    conversation = _require_admin_conversation(db, actor, conversation_id)
    owner = db.get(User, conversation.owner_user_id)
    messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at, Message.id)
        )
    )
    runs = list(
        db.scalars(
            select(Run)
            .where(Run.conversation_id == conversation.id)
            .order_by(Run.created_at, Run.id)
        )
    )
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(
                Artifact.conversation_id == conversation.id,
                Artifact.deleted_at.is_(None),
            )
            .order_by(Artifact.created_at, Artifact.id)
        )
    )
    feedback_rows = list(
        db.execute(
            select(MessageFeedback, User)
            .join(Message, Message.id == MessageFeedback.message_id)
            .join(User, User.id == MessageFeedback.user_id)
            .where(
                Message.conversation_id == conversation.id,
                MessageFeedback.deleted_at.is_(None),
            )
            .order_by(MessageFeedback.created_at.desc(), MessageFeedback.id.desc())
        ).all()
    )
    record_audit(
        db,
        action="admin_conversation_viewed",
        target_type="conversation",
        target_id=conversation.id,
        result="success",
        actor=actor,
        request_id=_request_id(request),
        metadata={"owner_user_id": conversation.owner_user_id},
    )
    db.commit()
    return {
        "conversation": {
            "id": conversation.id,
            "projectId": conversation.project_id,
            "title": conversation.title,
            "status": conversation.status,
            "owner": {
                "id": owner.id if owner else conversation.owner_user_id,
                "loginId": owner.login_id if owner else None,
                "displayName": owner.display_name if owner else None,
            },
            "createdAt": conversation.created_at,
            "updatedAt": conversation.updated_at,
        },
        "messages": [message_response(message, db) for message in messages],
        "runs": [run_snapshot(db, run) for run in runs],
        "artifacts": [
            {
                "id": artifact.id,
                "displayName": artifact.display_name,
                "kind": artifact.kind,
                "mimeType": artifact.mime_type,
                "currentVersion": artifact.current_version_number,
                "createdAt": artifact.created_at,
            }
            for artifact in artifacts
        ],
        "feedback": [
            {
                "id": feedback.id,
                "messageId": feedback.message_id,
                "kind": feedback.kind,
                "value": feedback.rating_value,
                "category": feedback.report_category,
                "description": feedback.report_description,
                "status": feedback.status,
                "author": {
                    "id": author.id,
                    "loginId": author.login_id,
                    "displayName": author.display_name,
                },
                "createdAt": feedback.created_at,
                "updatedAt": feedback.updated_at,
            }
            for feedback, author in feedback_rows
        ],
    }


@router.get("/conversations/{conversation_id}/turn-sets")
def get_admin_conversation_turn_sets(
    conversation_id: str,
    request: Request,
    limit_turn_sets: int = Query(default=20, ge=1, le=100),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    conversation = _require_admin_conversation(db, actor, conversation_id)
    runs = list(
        db.scalars(
            select(Run)
            .where(Run.conversation_id == conversation.id)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(limit_turn_sets)
        )
    )
    selected_run_ids = [run.id for run in runs]
    messages = (
        list(
            db.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.run_id.in_(selected_run_ids),
                )
                .order_by(Message.created_at, Message.id)
            )
        )
        if selected_run_ids
        else []
    )
    grouped: dict[str, list[Message]] = {run_id: [] for run_id in selected_run_ids}
    for message in messages:
        if message.run_id is not None:
            grouped.setdefault(message.run_id, []).append(message)
    record_audit(
        db,
        action="admin_conversation_viewed",
        target_type="conversation",
        target_id=conversation.id,
        result="success",
        actor=actor,
        request_id=_request_id(request),
        metadata={"view": "turn_sets"},
    )
    db.commit()
    return {
        "turnSets": [
            {
                "id": run.id,
                "runId": run.id,
                "messages": [
                    message_response(message, db) for message in grouped.get(run.id, [])
                ],
                "run": run_snapshot(db, run),
            }
            for run in reversed(runs)
        ],
        "hasMoreBefore": len(runs) == limit_turn_sets,
    }


@router.get("/audit-events")
def list_audit_events(
    request: Request,
    action: str | None = None,
    actor_user_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(actor)
    filters = [AuditEvent.organization_id == actor.organization_id]
    if action:
        filters.append(AuditEvent.action == action)
    if actor_user_id:
        filters.append(AuditEvent.actor_user_id == actor_user_id)
    if target_type:
        filters.append(AuditEvent.target_type == target_type)
    if target_id:
        filters.append(AuditEvent.target_id == target_id)
    if created_after:
        filters.append(AuditEvent.created_at >= created_after)
    if created_before:
        filters.append(AuditEvent.created_at <= created_before)

    total = int(db.scalar(select(func.count(AuditEvent.id)).where(*filters)) or 0)
    event_rows = list(
        db.execute(
            select(AuditEvent, User.login_id)
            .outerjoin(User, User.id == AuditEvent.actor_user_id)
            .where(*filters)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    record_audit(
        db,
        action="admin_audit_viewed",
        target_type="audit_event",
        result="success",
        actor=actor,
        request_id=_request_id(request),
        metadata={"filters_used": bool(filters[1:]), "offset": offset, "limit": limit},
    )
    db.commit()
    return {
        "items": [
            {
                "id": event.id,
                "organizationId": event.organization_id,
                "actorUserId": event.actor_user_id,
                "actorLoginId": actor_login_id,
                "action": event.action,
                "targetType": event.target_type,
                "targetId": event.target_id,
                "result": event.result,
                "requestId": event.request_id,
                "reason": event.reason,
                "metadata": event.metadata_json,
                "createdAt": event.created_at,
            }
            for event, actor_login_id in event_rows
        ],
        "total": total,
        "offset": offset,
        "hasMore": offset + len(event_rows) < total,
    }


@router.get("/audit-traffic")
def get_audit_traffic(
    request: Request,
    minutes: int = Query(default=60, ge=15, le=1440),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Return complete minute buckets for recent organization audit activity."""
    require_admin(actor)
    now = utc_now()
    window_end = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    window_start = window_end - timedelta(minutes=minutes)
    event_rows = list(
        db.execute(
            select(AuditEvent.created_at, AuditEvent.result).where(
                AuditEvent.organization_id == actor.organization_id,
                AuditEvent.created_at >= window_start,
                AuditEvent.created_at < window_end,
            )
        )
    )
    counts: dict[datetime, dict[str, int]] = {
        window_start + timedelta(minutes=index): {
            "normal": 0,
            "abnormal_audit": 0,
            "automatic_recovery": 0,
            "manual_restart": 0,
        }
        for index in range(minutes)
    }
    for event_time, result in event_rows:
        bucket = event_time.astimezone(UTC).replace(second=0, microsecond=0)
        if bucket in counts:
            key = "normal" if result == "success" else "abnormal_audit"
            counts[bucket][key] += 1
    for event_time, event in _launcher_monitoring_events(
        settings.data_dir / "logs" / "launcher-events.jsonl",
        window_start=window_start,
        window_end=window_end,
    ):
        bucket = event_time.replace(second=0, microsecond=0)
        if bucket in counts:
            counts[bucket][event] += 1

    record_audit(
        db,
        action="admin_audit_traffic_viewed",
        target_type="audit_event",
        result="success",
        actor=actor,
        request_id=_request_id(request),
        metadata={"minutes": minutes},
    )
    db.commit()
    buckets: list[dict[str, object]] = []
    bucket_values: list[int] = []
    normal_values: list[int] = []
    abnormal_values: list[int] = []
    for minute, bucket in counts.items():
        normal_count = bucket["normal"]
        abnormal_count = (
            bucket["abnormal_audit"]
            + bucket["automatic_recovery"]
            + bucket["manual_restart"]
        )
        total_count = normal_count + abnormal_count
        bucket_values.append(total_count)
        normal_values.append(normal_count)
        abnormal_values.append(abnormal_count)
        buckets.append(
            {
                "minute": minute,
                "count": total_count,
                "normalCount": normal_count,
                "abnormalCount": abnormal_count,
                "abnormalAuditCount": bucket["abnormal_audit"],
                "automaticRecoveryCount": bucket["automatic_recovery"],
                "manualRestartCount": bucket["manual_restart"],
            }
        )
    return {
        "generatedAt": now,
        "timezone": str(_ANALYTICS_TIMEZONE),
        "periodMinutes": minutes,
        "total": sum(bucket_values),
        "peak": max(bucket_values, default=0),
        "normalTotal": sum(normal_values),
        "normalPeak": max(normal_values, default=0),
        "abnormalTotal": sum(abnormal_values),
        "abnormalPeak": max(abnormal_values, default=0),
        "abnormalAuditTotal": sum(
            bucket["abnormal_audit"] for bucket in counts.values()
        ),
        "automaticRecoveryTotal": sum(
            bucket["automatic_recovery"] for bucket in counts.values()
        ),
        "manualRestartTotal": sum(
            bucket["manual_restart"] for bucket in counts.values()
        ),
        "buckets": buckets,
    }


def _admin_organization(db: Session, actor: User) -> Organization:
    require_admin(actor)
    organization = db.get(Organization, actor.organization_id)
    if organization is None:
        raise ApiProblem(404, "organization_not_found", "조직을 찾을 수 없습니다.")
    return organization


@router.get("/run-safety")
def get_run_safety_settings(
    request: Request,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int | float]:
    organization = _admin_organization(db, actor)
    record_audit(
        db,
        action="admin_run_safety_viewed",
        target_type="organization",
        target_id=organization.id,
        result="success",
        actor=actor,
        request_id=_request_id(request),
    )
    db.commit()
    return run_safety_payload(organization.run_safety_settings_json)


@router.patch("/run-safety")
def patch_run_safety_settings(
    payload: AdminRunSafetyPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, int | float]:
    organization = _admin_organization(db, context.user)
    previous = normalize_run_safety_settings(organization.run_safety_settings_json)
    updated = normalize_run_safety_settings(payload.model_dump())
    organization.run_safety_settings_json = updated
    record_audit(
        db,
        action="admin_run_safety_updated",
        target_type="organization",
        target_id=organization.id,
        result="unchanged" if previous == updated else "success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"previous": previous, "updated": updated},
    )
    db.commit()
    return run_safety_payload(updated)


@router.post("/run-safety/emergency-stop")
async def emergency_stop_all_runs(
    payload: AdminEmergencyStop,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    organization = _admin_organization(db, context.user)
    run_ids, queued_message_count = cancel_organization_work(
        db,
        organization_id=organization.id,
        actor_user_id=context.user.id,
    )
    record_audit(
        db,
        action="admin_all_runs_killed",
        target_type="organization",
        target_id=organization.id,
        result="success" if run_ids or queued_message_count else "unchanged",
        actor=context.user,
        request_id=_request_id(request),
        reason=payload.reason.strip() or None,
        metadata={
            "cancelled_run_count": len(run_ids),
            "cancelled_queued_message_count": queued_message_count,
        },
    )
    db.commit()
    active_task_count = local_run_executor.cancel_many(run_ids)
    if run_ids:
        await asyncio.gather(*(event_broker.notify(run_id) for run_id in run_ids))
    return {
        "cancelledRunCount": len(run_ids),
        "cancelledQueuedMessageCount": queued_message_count,
        "cancelledActiveTaskCount": active_task_count,
    }


@router.get("/conversation-shares")
def list_admin_shares(
    request: Request,
    active_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(actor)
    query = (
        select(ConversationShareGrant)
        .join(Conversation, Conversation.id == ConversationShareGrant.conversation_id)
        .where(Conversation.organization_id == actor.organization_id)
    )
    if active_only:
        query = query.where(ConversationShareGrant.revoked_at.is_(None))
    grants = list(
        db.scalars(
            query.order_by(ConversationShareGrant.created_at.desc()).limit(limit)
        )
    )
    record_audit(
        db,
        action="admin_share_list_viewed",
        target_type="conversation_share",
        result="success",
        actor=actor,
        request_id=_request_id(request),
    )
    db.commit()
    return {
        "items": [
            {
                "id": grant.id,
                "conversationId": grant.conversation_id,
                "ownerUserId": grant.owner_user_id,
                "recipientUserId": grant.recipient_user_id,
                "scope": grant.scope,
                "anchorMessageId": grant.anchor_message_id,
                "snapshotThroughMessageId": grant.snapshot_through_message_id,
                "expiresAt": grant.expires_at,
                "revokedAt": grant.revoked_at,
                "createdAt": grant.created_at,
                "lastAccessedAt": grant.last_accessed_at,
            }
            for grant in grants
        ]
    }


@router.delete("/conversation-shares/{share_id}", status_code=204)
def revoke_admin_share(
    share_id: str,
    payload: AdminShareRevoke,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    require_admin(context.user)
    grant = db.scalar(
        select(ConversationShareGrant)
        .join(Conversation, Conversation.id == ConversationShareGrant.conversation_id)
        .where(
            ConversationShareGrant.id == share_id,
            Conversation.organization_id == context.user.organization_id,
        )
    )
    if grant is None:
        raise ApiProblem(404, "share_not_found", "공유 권한을 찾을 수 없습니다.")
    already_revoked = grant.revoked_at is not None
    if not already_revoked:
        grant.revoked_at = utc_now()
    record_audit(
        db,
        action="admin_share_force_revoked",
        target_type="conversation_share",
        target_id=grant.id,
        result="unchanged" if already_revoked else "success",
        actor=context.user,
        request_id=_request_id(request),
        reason=payload.reason.strip() or None,
        metadata={
            "conversation_id": grant.conversation_id,
            "owner_user_id": grant.owner_user_id,
            "recipient_user_id": grant.recipient_user_id,
        },
    )
    db.commit()
    return Response(status_code=204)
