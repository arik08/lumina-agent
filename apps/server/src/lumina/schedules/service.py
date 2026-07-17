from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..api.schemas import (
    ExecutionSelection,
    RunActionRequest,
    RunCreate,
    RunMessageInput,
)
from ..authorization import require_conversation, require_project
from ..db import SessionLocal
from ..extensions.service import resolve_skill_snapshot
from ..models import (
    Artifact,
    Conversation,
    Project,
    ProjectMembership,
    Run,
    ScheduledRun,
    ScheduledTask,
    User,
    utc_now,
)
from ..notifications import create_scheduled_run_result_notification
from ..runs.service import apply_run_action, create_run, resolve_execution
from ..runs.state import TERMINAL_STATUSES
from ..secret_policy import reject_secret_key_names
from .schemas import CONTEXT_MODES, EXTENSION_SNAPSHOT_POLICIES, SCHEDULE_KINDS


_ACTIVE_SCHEDULED_RUN_STATUSES = {"queued", "running", "retry_waiting"}
_RETRYABLE_RUN_STATUSES = {"failed", "interrupted", "limit_reached"}
_SCHEDULED_TIMEOUT_CODE = "scheduled_timeout"
_MIN_TIMEOUT_SECONDS = 30
_MAX_TIMEOUT_SECONDS = 86_400
_MIN_ATTEMPTS = 1
_MAX_ATTEMPTS = 10


def _reject_secrets(value: Any, path: str) -> None:
    reject_secret_key_names(value, path=path)


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ApiProblem(
            422, "invalid_timezone", "지원하지 않는 시간대입니다."
        ) from exc


def normalize_schedule_config(kind: str, config: dict[str, Any]) -> dict[str, int]:
    if kind not in SCHEDULE_KINDS:
        raise ApiProblem(422, "invalid_schedule_kind", "지원하지 않는 예약 유형입니다.")
    if kind == "manual":
        return {}
    allowed = {"minute"} if kind == "hourly" else {"hour", "minute"}
    if kind == "weekly":
        allowed.add("weekday")
    unknown = set(config) - allowed
    if unknown:
        raise ApiProblem(
            422, "invalid_schedule_config", "예약 설정 항목이 올바르지 않습니다."
        )

    def integer(name: str, default: int, minimum: int, maximum: int) -> int:
        raw = config.get(name, default)
        if (
            isinstance(raw, bool)
            or not isinstance(raw, int)
            or not minimum <= raw <= maximum
        ):
            raise ApiProblem(
                422, "invalid_schedule_config", f"{name} 값이 올바르지 않습니다."
            )
        return raw

    result = {"minute": integer("minute", 0, 0, 59)}
    if kind != "hourly":
        result["hour"] = integer("hour", 9, 0, 23)
    if kind == "weekly":
        result["weekday"] = integer("weekday", 0, 0, 6)
    return result


def next_occurrence(
    *,
    kind: str,
    config: dict[str, Any],
    timezone: str,
    after: datetime,
) -> datetime | None:
    normalized = normalize_schedule_config(kind, config)
    if kind == "manual":
        return None
    if after.tzinfo is None:
        raise ValueError("after must include timezone information")
    zone = _timezone(timezone)
    local_after = after.astimezone(zone)
    if kind == "hourly":
        candidate = local_after.replace(
            minute=normalized["minute"], second=0, microsecond=0
        )
        if candidate <= local_after:
            candidate += timedelta(hours=1)
        return candidate.astimezone(UTC)
    candidate = local_after.replace(
        hour=normalized["hour"],
        minute=normalized["minute"],
        second=0,
        microsecond=0,
    )
    if kind == "daily":
        if candidate <= local_after:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC)
    if kind == "weekdays":
        if candidate <= local_after:
            candidate += timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC)
    days = (normalized["weekday"] - candidate.weekday()) % 7
    candidate += timedelta(days=days)
    if candidate <= local_after:
        candidate += timedelta(days=7)
    return candidate.astimezone(UTC)


def require_scheduled_task(
    db: Session, user: User, task_id: str, *, write: bool = False
) -> ScheduledTask:
    task = db.get(ScheduledTask, task_id)
    if task is None or task.archived_at is not None:
        raise ApiProblem(
            404, "scheduled_task_not_found", "예약 작업을 찾을 수 없습니다."
        )
    require_project(db, user, task.project_id, write=write)
    return task


def create_scheduled_task(
    db: Session,
    *,
    user: User,
    project_id: str,
    name: str,
    instructions: str,
    schedule_kind: str,
    schedule_config: dict[str, Any],
    timezone: str,
    context_mode: str,
    source_conversation_id: str | None,
    execution: ExecutionSelection,
    extension_snapshot_policy: str,
    delivery_policy: dict[str, Any],
    enabled: bool,
    max_attempts: int,
    timeout_seconds: int,
    now: datetime | None = None,
) -> ScheduledTask:
    project = require_project(db, user, project_id, write=True)
    _validate_context(
        db,
        user=user,
        project_id=project.id,
        context_mode=context_mode,
        source_conversation_id=source_conversation_id,
    )
    normalized_config = normalize_schedule_config(schedule_kind, schedule_config)
    _timezone(timezone)
    if extension_snapshot_policy not in EXTENSION_SNAPSHOT_POLICIES:
        raise ApiProblem(
            422, "invalid_extension_policy", "확장 snapshot 정책이 올바르지 않습니다."
        )
    _reject_secrets(delivery_policy, "deliveryPolicy")
    extension_policy: dict[str, Any] = {"mode": extension_snapshot_policy}
    if extension_snapshot_policy == "pinned":
        extension_policy["snapshot"] = resolve_skill_snapshot(
            db, user=user, project_id=project.id
        )
    current = now or utc_now()
    resolved_execution = _validated_execution(db, execution)
    task = ScheduledTask(
        organization_id=user.organization_id,
        project_id=project.id,
        owner_user_id=user.id,
        name=name.strip(),
        instructions=instructions,
        schedule_kind=schedule_kind,
        schedule_config_json=normalized_config,
        timezone=timezone,
        context_mode=context_mode,
        source_conversation_id=source_conversation_id,
        provider_id=resolved_execution.provider_id,
        model_key=resolved_execution.model_key,
        effort=resolved_execution.effort_id,
        extension_policy_json=extension_policy,
        delivery_policy_json=delivery_policy,
        enabled=enabled,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
        next_run_at=(
            next_occurrence(
                kind=schedule_kind,
                config=normalized_config,
                timezone=timezone,
                after=current,
            )
            if enabled
            else None
        ),
    )
    db.add(task)
    db.flush()
    return task


def _validate_context(
    db: Session,
    *,
    user: User,
    project_id: str,
    context_mode: str,
    source_conversation_id: str | None,
) -> None:
    if context_mode not in CONTEXT_MODES:
        raise ApiProblem(
            422, "invalid_context_mode", "예약 작업 Context 방식이 올바르지 않습니다."
        )
    if context_mode == "continue_session" and source_conversation_id is None:
        raise ApiProblem(
            422,
            "source_conversation_required",
            "이어 실행할 대화를 선택해 주세요.",
        )
    if source_conversation_id is not None:
        conversation = require_conversation(
            db, user, source_conversation_id, write=True
        )
        if conversation.project_id != project_id:
            raise ApiProblem(
                409,
                "source_project_mismatch",
                "원본 대화가 예약 작업 Project에 속하지 않습니다.",
            )


def list_scheduled_tasks(
    db: Session, *, user: User, project_id: str | None = None
) -> list[ScheduledTask]:
    if project_id is not None:
        require_project(db, user, project_id)
        project_ids = [project_id]
    elif user.role == "admin":
        project_ids = list(db.scalars(select(Project.id)))
    else:
        owned = select(Project.id).where(Project.owner_user_id == user.id)
        member = select(ProjectMembership.project_id).where(
            ProjectMembership.user_id == user.id,
            ProjectMembership.status == "active",
        )
        project_ids = list(db.scalars(owned.union(member)))
    if not project_ids:
        return []
    return list(
        db.scalars(
            select(ScheduledTask)
            .where(
                ScheduledTask.project_id.in_(project_ids),
                ScheduledTask.archived_at.is_(None),
            )
            .order_by(ScheduledTask.updated_at.desc(), ScheduledTask.id)
        )
    )


def update_scheduled_task(
    db: Session,
    *,
    user: User,
    task_id: str,
    changes: dict[str, Any],
    now: datetime | None = None,
) -> ScheduledTask:
    task = require_scheduled_task(db, user, task_id, write=True)
    project_id = str(changes.get("project_id", task.project_id))
    project_changed = project_id != task.project_id
    if project_changed:
        require_project(db, user, project_id, write=True)
    schedule_kind = changes.get("schedule_kind", task.schedule_kind)
    schedule_config = changes.get("schedule_config", task.schedule_config_json)
    timezone = changes.get("timezone", task.timezone)
    context_mode = changes.get("context_mode", task.context_mode)
    source_conversation_id = changes.get(
        "source_conversation_id", task.source_conversation_id
    )
    _validate_context(
        db,
        user=user,
        project_id=project_id,
        context_mode=context_mode,
        source_conversation_id=source_conversation_id,
    )
    normalized_config = normalize_schedule_config(schedule_kind, schedule_config)
    _timezone(timezone)
    if "name" in changes:
        task.name = str(changes["name"]).strip()
    if "instructions" in changes:
        task.instructions = str(changes["instructions"])
    task.project_id = project_id
    task.schedule_kind = schedule_kind
    task.schedule_config_json = normalized_config
    task.timezone = timezone
    task.context_mode = context_mode
    task.source_conversation_id = source_conversation_id
    execution = changes.get("execution")
    if execution is not None:
        resolved_execution = _validated_execution(
            db,
            ExecutionSelection(
                provider_id=str(execution["provider_id"]),
                model_key=str(execution["model_key"]),
                effort_id=execution.get("effort_id"),
            ),
        )
        task.provider_id = resolved_execution.provider_id
        task.model_key = resolved_execution.model_key
        task.effort = resolved_execution.effort_id
    extension_mode = changes.get("extension_snapshot_policy")
    if extension_mode is not None or project_changed:
        extension_mode = extension_mode or task.extension_policy_json.get("mode", "pinned")
        if extension_mode not in EXTENSION_SNAPSHOT_POLICIES:
            raise ApiProblem(
                422,
                "invalid_extension_policy",
                "확장 snapshot 정책이 올바르지 않습니다.",
            )
        task.extension_policy_json = {"mode": extension_mode}
        if extension_mode == "pinned":
            task.extension_policy_json["snapshot"] = resolve_skill_snapshot(
                db, user=user, project_id=project_id
            )
    if "delivery_policy" in changes:
        delivery_policy = changes["delivery_policy"]
        _reject_secrets(delivery_policy, "deliveryPolicy")
        task.delivery_policy_json = delivery_policy
    if "max_attempts" in changes:
        task.max_attempts = int(changes["max_attempts"])
    if "timeout_seconds" in changes:
        task.timeout_seconds = int(changes["timeout_seconds"])
    current = now or utc_now()
    task.next_run_at = (
        next_occurrence(
            kind=task.schedule_kind,
            config=task.schedule_config_json,
            timezone=task.timezone,
            after=current,
        )
        if task.enabled
        else None
    )
    task.updated_at = current
    db.flush()
    return task


def set_scheduled_task_enabled(
    db: Session,
    *,
    user: User,
    task_id: str,
    enabled: bool,
    now: datetime | None = None,
) -> ScheduledTask:
    task = require_scheduled_task(db, user, task_id, write=True)
    current = now or utc_now()
    task.enabled = enabled
    task.next_run_at = (
        next_occurrence(
            kind=task.schedule_kind,
            config=task.schedule_config_json,
            timezone=task.timezone,
            after=current,
        )
        if enabled
        else None
    )
    task.updated_at = current
    db.flush()
    return task


def archive_scheduled_task(db: Session, *, user: User, task_id: str) -> ScheduledTask:
    task = require_scheduled_task(db, user, task_id, write=True)
    task.enabled = False
    task.next_run_at = None
    task.archived_at = utc_now()
    task.updated_at = task.archived_at
    db.flush()
    return task


def _execution_extension_snapshot(
    db: Session, task: ScheduledTask, user: User
) -> list[dict[str, Any]]:
    mode = task.extension_policy_json.get("mode", "pinned")
    if mode == "pinned":
        return list(task.extension_policy_json.get("snapshot", []))
    return resolve_skill_snapshot(db, user=user, project_id=task.project_id)


def _validated_execution(
    db: Session, selection: ExecutionSelection
) -> ExecutionSelection:
    resolved = resolve_execution(
        db,
        RunCreate(
            message=RunMessageInput(text="scheduled task validation"),
            execution=selection,
        ),
    )
    if (
        resolved["provider_id"] != selection.provider_id
        or resolved["model_key"] != selection.model_key
    ):
        raise ApiProblem(
            409,
            "scheduled_model_unavailable",
            "예약 작업에 선택한 Provider 또는 Model을 사용할 수 없습니다.",
        )
    return ExecutionSelection(
        provider_id=resolved["provider_id"],
        model_key=resolved["model_key"],
        effort_id=resolved["effort"],
    )


def _delivery_policy_snapshot(policy: dict[str, Any]) -> dict[str, Any]:
    """In-app history is the mandatory delivery channel for the initial server."""

    return {**policy, "in_app": True}


def _snapshot_integer(
    scheduled_run: ScheduledRun,
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = scheduled_run.input_snapshot_json.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return min(max(value, minimum), maximum)


def _max_attempts(scheduled_run: ScheduledRun) -> int:
    return _snapshot_integer(
        scheduled_run,
        "max_attempts",
        default=1,
        minimum=_MIN_ATTEMPTS,
        maximum=_MAX_ATTEMPTS,
    )


def _timeout_seconds(scheduled_run: ScheduledRun) -> int:
    return _snapshot_integer(
        scheduled_run,
        "timeout_seconds",
        default=900,
        minimum=_MIN_TIMEOUT_SECONDS,
        maximum=_MAX_TIMEOUT_SECONDS,
    )


def _retry_delay(attempt: int) -> timedelta:
    bounded_attempt = min(max(attempt, 1), _MAX_ATTEMPTS)
    return timedelta(seconds=min(5 * (2 ** (bounded_attempt - 1)), 300))


def _is_retryable_terminal(run: Run | None) -> bool:
    if run is None:
        return True
    return run.status in _RETRYABLE_RUN_STATUSES or (
        run.status == "cancelled" and run.error_code == _SCHEDULED_TIMEOUT_CODE
    )


def _patch_scheduled_run_snapshot(
    run: Run,
    *,
    scheduled_run: ScheduledRun,
    extensions: list[dict[str, Any]],
    delivery_policy: dict[str, Any],
    previous_run_id: str | None = None,
) -> None:
    run.snapshot_json = {
        **run.snapshot_json,
        "scheduled_run_id": scheduled_run.id,
        "scheduled_task_id": scheduled_run.scheduled_task_id,
        "scheduled_attempt": scheduled_run.attempt,
        "scheduled_timeout_seconds": _timeout_seconds(scheduled_run),
        "extensions": extensions,
        "delivery_policy": delivery_policy,
        "previous_scheduled_run_attempt_id": previous_run_id,
    }


def start_scheduled_run(
    db: Session,
    *,
    user: User,
    task: ScheduledTask,
    trigger_type: str,
    scheduled_for: datetime,
    idempotency_key: str,
) -> tuple[ScheduledRun, bool]:
    def existing_occurrence() -> ScheduledRun | None:
        return db.scalar(
            select(ScheduledRun).where(
                ScheduledRun.scheduled_task_id == task.id,
                or_(
                    ScheduledRun.idempotency_key == idempotency_key,
                    ScheduledRun.scheduled_for == scheduled_for,
                ),
            )
        )

    existing = existing_occurrence()
    if existing is not None:
        return existing, False
    extension_snapshot = _execution_extension_snapshot(db, task, user)
    delivery_policy = _delivery_policy_snapshot(task.delivery_policy_json)
    snapshot = {
        "scheduled_task_id": task.id,
        "task_updated_at": task.updated_at.isoformat(),
        "instructions": task.instructions,
        "project_id": task.project_id,
        "context_mode": task.context_mode,
        "source_conversation_id": task.source_conversation_id,
        "execution": {
            "provider_id": task.provider_id,
            "model_key": task.model_key,
            "effort_id": task.effort,
        },
        "extensions": extension_snapshot,
        "delivery_policy": delivery_policy,
        "timeout_seconds": task.timeout_seconds,
        "max_attempts": task.max_attempts,
    }
    scheduled_run = ScheduledRun(
        scheduled_task_id=task.id,
        requested_by_user_id=user.id,
        trigger_type=trigger_type,
        scheduled_for=scheduled_for,
        idempotency_key=idempotency_key,
        input_snapshot_json=snapshot,
        status="queued",
        attempt=1,
    )
    try:
        with db.begin_nested():
            db.add(scheduled_run)
            db.flush()
    except IntegrityError:
        existing = existing_occurrence()
        if existing is None:
            raise
        return existing, False
    conversation = _scheduled_conversation(
        db, user=user, task=task, scheduled_run=scheduled_run
    )
    run, _message, _created = create_run(
        db,
        user=user,
        conversation_id=conversation.id,
        payload=RunCreate(
            message=RunMessageInput(text=task.instructions),
            execution=ExecutionSelection(
                provider_id=task.provider_id,
                model_key=task.model_key,
                effort_id=task.effort,
            ),
        ),
        idempotency_key=f"scheduled-run:{scheduled_run.id}:attempt:1",
        extension_snapshot_override=extension_snapshot,
        apply_extension_snapshot=True,
    )
    _patch_scheduled_run_snapshot(
        run,
        scheduled_run=scheduled_run,
        extensions=extension_snapshot,
        delivery_policy=delivery_policy,
    )
    scheduled_run.run_id = run.id
    task.last_run_at = scheduled_for
    if trigger_type == "scheduled":
        task.next_run_at = next_occurrence(
            kind=task.schedule_kind,
            config=task.schedule_config_json,
            timezone=task.timezone,
            after=scheduled_for,
        )
    db.flush()
    return scheduled_run, True


def _scheduled_conversation(
    db: Session, *, user: User, task: ScheduledTask, scheduled_run: ScheduledRun
) -> Conversation:
    if task.context_mode == "continue_session":
        if task.source_conversation_id is None:
            raise ApiProblem(
                409,
                "source_conversation_missing",
                "이어 실행할 원본 대화가 없습니다.",
            )
        conversation = require_conversation(
            db, user, task.source_conversation_id, write=True
        )
    else:
        conversation = Conversation(
            organization_id=task.organization_id,
            project_id=task.project_id,
            owner_user_id=user.id,
            title=f"[예약] {task.name}",
            visibility="private",
            status="active",
            agent_id="general",
            agent_version="1",
        )
        db.add(conversation)
        db.flush()
    scheduled_run.input_snapshot_json = {
        **scheduled_run.input_snapshot_json,
        "conversation_id": conversation.id,
    }
    return conversation


def dispatch_due_tasks(
    db: Session, *, now: datetime | None = None
) -> list[ScheduledRun]:
    current = now or utc_now()
    due_tasks = list(
        db.scalars(
            select(ScheduledTask)
            .where(
                ScheduledTask.enabled.is_(True),
                ScheduledTask.archived_at.is_(None),
                ScheduledTask.next_run_at.is_not(None),
                ScheduledTask.next_run_at <= current,
            )
            .order_by(ScheduledTask.next_run_at, ScheduledTask.id)
            .with_for_update(skip_locked=True)
        )
    )
    created: list[ScheduledRun] = []
    for task in due_tasks:
        if task.next_run_at is None:
            continue
        owner = db.get(User, task.owner_user_id)
        if owner is None or owner.status != "active":
            task.enabled = False
            task.next_run_at = None
            continue
        scheduled_for = task.next_run_at
        scheduled_run, was_created = start_scheduled_run(
            db,
            user=owner,
            task=task,
            trigger_type="scheduled",
            scheduled_for=scheduled_for,
            idempotency_key=f"schedule:{scheduled_for.isoformat()}",
        )
        if was_created:
            created.append(scheduled_run)
    return created


def _artifact_ids_for_run(db: Session, run_id: str) -> list[str]:
    return list(
        db.scalars(
            select(Artifact.id)
            .where(Artifact.source_run_id == run_id)
            .order_by(Artifact.created_at, Artifact.id)
        )
    )


def _terminal_error(run: Run) -> tuple[str | None, str | None]:
    if run.status == "completed":
        return None, None
    default_messages = {
        "failed": "Run 실행에 실패했습니다.",
        "interrupted": "서버 재시작으로 Run이 중단되었습니다.",
        "limit_reached": "이전 버전에서 Run이 중단되었습니다.",
        "cancelled": "Run이 취소되었습니다.",
    }
    return (
        run.error_code or f"run_{run.status}",
        run.error_message
        or default_messages.get(run.status, "Run이 정상적으로 완료되지 않았습니다."),
    )


def reconcile_scheduled_run(
    db: Session,
    scheduled_run: ScheduledRun,
    *,
    now: datetime | None = None,
) -> ScheduledRun:
    current = now or utc_now()
    if scheduled_run.run_id is None:
        scheduled_run.error_code = "run_missing"
        scheduled_run.error_message = "연결된 Run을 찾을 수 없습니다."
        scheduled_run.finished_at = scheduled_run.finished_at or current
        scheduled_run.status = (
            "retry_waiting"
            if scheduled_run.attempt < _max_attempts(scheduled_run)
            else "failed"
        )
        create_scheduled_run_result_notification(db, scheduled_run)
        return scheduled_run

    run = db.get(Run, scheduled_run.run_id)
    if run is None:
        scheduled_run.error_code = "run_missing"
        scheduled_run.error_message = "연결된 Run을 찾을 수 없습니다."
        scheduled_run.finished_at = scheduled_run.finished_at or current
        scheduled_run.status = (
            "retry_waiting"
            if scheduled_run.attempt < _max_attempts(scheduled_run)
            else "failed"
        )
        create_scheduled_run_result_notification(db, scheduled_run)
        return scheduled_run

    if run.status == "queued":
        scheduled_run.status = "queued"
        scheduled_run.error_code = None
        scheduled_run.error_message = None
    elif run.status in TERMINAL_STATUSES:
        scheduled_run.started_at = run.started_at
        scheduled_run.finished_at = (
            run.finished_at or scheduled_run.finished_at or current
        )
        scheduled_run.output_artifact_ids_json = _artifact_ids_for_run(db, run.id)
        scheduled_run.error_code, scheduled_run.error_message = _terminal_error(run)
        if run.status == "completed":
            scheduled_run.status = "completed"
        elif _is_retryable_terminal(run) and scheduled_run.attempt < _max_attempts(
            scheduled_run
        ):
            scheduled_run.status = "retry_waiting"
        elif run.error_code == _SCHEDULED_TIMEOUT_CODE:
            scheduled_run.status = "failed"
        else:
            scheduled_run.status = run.status
    else:
        scheduled_run.status = "running"
        scheduled_run.started_at = run.started_at
        scheduled_run.error_code = None
        scheduled_run.error_message = None
    create_scheduled_run_result_notification(db, scheduled_run)
    return scheduled_run


def _retry_is_due(scheduled_run: ScheduledRun, current: datetime) -> bool:
    terminal_at = scheduled_run.finished_at or scheduled_run.created_at
    return current >= terminal_at + _retry_delay(scheduled_run.attempt)


def _snapshot_execution(scheduled_run: ScheduledRun) -> ExecutionSelection:
    raw = scheduled_run.input_snapshot_json.get("execution")
    if not isinstance(raw, dict):
        raise ApiProblem(
            409,
            "scheduled_snapshot_invalid",
            "예약 실행의 Provider snapshot이 올바르지 않습니다.",
        )
    provider_id = raw.get("provider_id")
    model_key = raw.get("model_key")
    effort_id = raw.get("effort_id")
    if not isinstance(provider_id, str) or not isinstance(model_key, str):
        raise ApiProblem(
            409,
            "scheduled_snapshot_invalid",
            "예약 실행의 Provider snapshot이 올바르지 않습니다.",
        )
    return ExecutionSelection(
        provider_id=provider_id,
        model_key=model_key,
        effort_id=effort_id if isinstance(effort_id, str) else None,
    )


def _snapshot_extensions(scheduled_run: ScheduledRun) -> list[dict[str, Any]]:
    raw = scheduled_run.input_snapshot_json.get("extensions", [])
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ApiProblem(
            409,
            "scheduled_snapshot_invalid",
            "예약 실행의 Extension snapshot이 올바르지 않습니다.",
        )
    return [dict(item) for item in raw]


def _start_retry_attempt(
    db: Session,
    *,
    scheduled_run: ScheduledRun,
    task: ScheduledTask,
    user: User,
) -> Run:
    if task.archived_at is not None:
        raise ApiProblem(
            409, "scheduled_task_archived", "보관된 예약 작업은 재시도할 수 없습니다."
        )
    conversation_id = scheduled_run.input_snapshot_json.get("conversation_id")
    instructions = scheduled_run.input_snapshot_json.get("instructions")
    if not isinstance(conversation_id, str) or not isinstance(instructions, str):
        raise ApiProblem(
            409,
            "scheduled_snapshot_invalid",
            "예약 실행의 입력 snapshot이 올바르지 않습니다.",
        )
    conversation = require_conversation(db, user, conversation_id, write=True)
    if conversation.project_id != task.project_id:
        raise ApiProblem(
            409,
            "scheduled_snapshot_invalid",
            "예약 실행의 Project snapshot이 현재 작업과 일치하지 않습니다.",
        )
    execution = _validated_execution(db, _snapshot_execution(scheduled_run))
    extensions = _snapshot_extensions(scheduled_run)
    raw_delivery_policy = scheduled_run.input_snapshot_json.get("delivery_policy", {})
    if not isinstance(raw_delivery_policy, dict):
        raise ApiProblem(
            409,
            "scheduled_snapshot_invalid",
            "예약 실행의 전달 정책 snapshot이 올바르지 않습니다.",
        )
    delivery_policy = _delivery_policy_snapshot(raw_delivery_policy)
    previous_run_id = scheduled_run.run_id
    next_attempt = scheduled_run.attempt + 1
    run, _message, _created = create_run(
        db,
        user=user,
        conversation_id=conversation.id,
        payload=RunCreate(
            message=RunMessageInput(text=instructions),
            execution=execution,
        ),
        idempotency_key=(f"scheduled-run:{scheduled_run.id}:attempt:{next_attempt}"),
        extension_snapshot_override=extensions,
        apply_extension_snapshot=True,
    )
    scheduled_run.attempt = next_attempt
    run.parent_run_id = previous_run_id
    _patch_scheduled_run_snapshot(
        run,
        scheduled_run=scheduled_run,
        extensions=extensions,
        delivery_policy=delivery_policy,
        previous_run_id=previous_run_id,
    )
    scheduled_run.run_id = run.id
    scheduled_run.status = "queued"
    scheduled_run.output_artifact_ids_json = []
    scheduled_run.error_code = None
    scheduled_run.error_message = None
    scheduled_run.started_at = None
    scheduled_run.finished_at = None
    db.flush()
    return run


def _mark_retry_unavailable(
    db: Session,
    scheduled_run: ScheduledRun,
    *,
    code: str,
    message: str,
    current: datetime,
) -> None:
    scheduled_run.status = "failed"
    scheduled_run.error_code = code
    scheduled_run.error_message = message
    scheduled_run.finished_at = scheduled_run.finished_at or current
    create_scheduled_run_result_notification(db, scheduled_run)


def _run_has_timed_out(
    scheduled_run: ScheduledRun, run: Run, current: datetime
) -> bool:
    if run.status in TERMINAL_STATUSES:
        return False
    timeout_origin = run.started_at or run.queued_at
    return current >= timeout_origin + timedelta(
        seconds=_timeout_seconds(scheduled_run)
    )


def maintain_scheduled_runs(
    db: Session, *, now: datetime | None = None
) -> tuple[list[str], list[str]]:
    """Reconcile active occurrences and return (enqueue IDs, notify IDs)."""

    current = now or utc_now()
    scheduled_runs = list(
        db.scalars(
            select(ScheduledRun)
            .where(ScheduledRun.status.in_(_ACTIVE_SCHEDULED_RUN_STATUSES))
            .order_by(ScheduledRun.created_at, ScheduledRun.id)
            .with_for_update(skip_locked=True)
        )
    )
    enqueue_ids: list[str] = []
    notify_ids: list[str] = []
    for scheduled_run in scheduled_runs:
        run = db.get(Run, scheduled_run.run_id) if scheduled_run.run_id else None
        user = db.get(User, scheduled_run.requested_by_user_id)
        if run is not None and _run_has_timed_out(scheduled_run, run, current):
            if user is None:
                _mark_retry_unavailable(
                    db,
                    scheduled_run,
                    code="scheduled_user_missing",
                    message="예약 실행 사용자를 찾을 수 없어 timeout 취소를 처리하지 못했습니다.",
                    current=current,
                )
                continue
            run.error_code = _SCHEDULED_TIMEOUT_CODE
            run.error_message = f"예약 실행 제한 시간({_timeout_seconds(scheduled_run)}초)을 초과했습니다."
            apply_run_action(
                db,
                user=user,
                run_id=run.id,
                payload=RunActionRequest(type="cancel"),
                idempotency_key=(
                    f"scheduled-timeout:{scheduled_run.id}:attempt:{scheduled_run.attempt}"
                ),
            )
            run.finished_at = current
            notify_ids.append(run.id)

        reconcile_scheduled_run(db, scheduled_run, now=current)
        if scheduled_run.status != "retry_waiting" or not _retry_is_due(
            scheduled_run, current
        ):
            continue
        task = db.get(ScheduledTask, scheduled_run.scheduled_task_id)
        if task is None or task.archived_at is not None:
            _mark_retry_unavailable(
                db,
                scheduled_run,
                code="scheduled_task_unavailable",
                message="예약 작업이 삭제되었거나 보관되어 재시도할 수 없습니다.",
                current=current,
            )
            continue
        if user is None or user.status != "active":
            _mark_retry_unavailable(
                db,
                scheduled_run,
                code="scheduled_user_unavailable",
                message="예약 실행 사용자가 비활성 상태라 재시도할 수 없습니다.",
                current=current,
            )
            continue
        try:
            retry_run = _start_retry_attempt(
                db,
                scheduled_run=scheduled_run,
                task=task,
                user=user,
            )
        except ApiProblem as problem:
            _mark_retry_unavailable(
                db,
                scheduled_run,
                code=problem.code,
                message=problem.message,
                current=current,
            )
        else:
            enqueue_ids.append(retry_run.id)
    db.flush()
    return enqueue_ids, notify_ids


def list_scheduled_runs(
    db: Session, *, user: User, task_id: str, limit: int = 50
) -> list[ScheduledRun]:
    task = require_scheduled_task(db, user, task_id)
    rows = list(
        db.scalars(
            select(ScheduledRun)
            .where(ScheduledRun.scheduled_task_id == task.id)
            .order_by(ScheduledRun.created_at.desc(), ScheduledRun.id)
            .limit(limit)
        )
    )
    for row in rows:
        reconcile_scheduled_run(db, row)
    return rows


def scheduled_task_payload(task: ScheduledTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "projectId": task.project_id,
        "name": task.name,
        "instructions": task.instructions,
        "scheduleKind": task.schedule_kind,
        "scheduleConfig": task.schedule_config_json,
        "timezone": task.timezone,
        "contextMode": task.context_mode,
        "sourceConversationId": task.source_conversation_id,
        "execution": {
            "providerId": task.provider_id,
            "modelKey": task.model_key,
            "effortId": task.effort,
        },
        "extensionSnapshotPolicy": task.extension_policy_json.get("mode", "pinned"),
        "deliveryPolicy": task.delivery_policy_json,
        "enabled": task.enabled,
        "maxAttempts": task.max_attempts,
        "timeoutSeconds": task.timeout_seconds,
        "nextRunAt": task.next_run_at,
        "lastRunAt": task.last_run_at,
        "createdAt": task.created_at,
        "updatedAt": task.updated_at,
    }


def scheduled_run_payload(scheduled_run: ScheduledRun) -> dict[str, Any]:
    if scheduled_run.status == "completed":
        delivery_status = "available"
    elif scheduled_run.status == "cancelled":
        delivery_status = "cancelled"
    elif scheduled_run.status in {
        "failed",
        "interrupted",
        "limit_reached",
    }:
        delivery_status = "failed"
    else:
        delivery_status = "pending"
    return {
        "id": scheduled_run.id,
        "scheduledTaskId": scheduled_run.scheduled_task_id,
        "triggerType": scheduled_run.trigger_type,
        "scheduledFor": scheduled_run.scheduled_for,
        "status": scheduled_run.status,
        "attempt": scheduled_run.attempt,
        "runId": scheduled_run.run_id,
        "inputSnapshot": scheduled_run.input_snapshot_json,
        "outputArtifactIds": scheduled_run.output_artifact_ids_json,
        "delivery": {
            "channel": "in_app",
            "status": delivery_status,
            "outputArtifactIds": scheduled_run.output_artifact_ids_json,
            "completedAt": (
                scheduled_run.finished_at
                if delivery_status in {"available", "cancelled", "failed"}
                else None
            ),
        },
        "error": (
            {
                "code": scheduled_run.error_code,
                "message": scheduled_run.error_message,
            }
            if scheduled_run.error_code
            else None
        ),
        "createdAt": scheduled_run.created_at,
        "startedAt": scheduled_run.started_at,
        "finishedAt": scheduled_run.finished_at,
    }


class LocalScheduler:
    """Single-process scheduler contract; DB remains the source of truth."""

    async def tick(self, *, now: datetime | None = None) -> list[str]:
        from ..agent.executor import local_run_executor
        from ..runs.broker import event_broker

        with SessionLocal() as db:
            retry_run_ids, notify_run_ids = maintain_scheduled_runs(db, now=now)
            scheduled_runs = dispatch_due_tasks(db, now=now)
            run_ids = [
                *retry_run_ids,
                *(item.run_id for item in scheduled_runs if item.run_id),
            ]
            db.commit()
        for run_id in notify_run_ids:
            await event_broker.notify(run_id)
        for run_id in run_ids:
            local_run_executor.enqueue(run_id)
        return run_ids


local_scheduler = LocalScheduler()
