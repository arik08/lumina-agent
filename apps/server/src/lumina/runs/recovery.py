from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection

from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Plan, PlanStep, PlanSubtask, Run, ToolExecution, utc_now
from .plans import resume_plan
from .service import append_event, plan_snapshot, transition_run
from .state import (
    ACTIVE_STATUSES,
    AWAITING_APPROVAL,
    AWAITING_INPUT,
    INTERRUPTED,
    PAUSED,
    QUEUED,
)
from .subtasks import finish_tool_subtask


@dataclass(frozen=True, slots=True)
class WorkerRecoveryBatch:
    resumable_run_ids: tuple[str, ...]
    waiting_run_ids: tuple[str, ...]


def prepare_worker_recovery(
    db: Session,
    *,
    protected_run_ids: Collection[str] = (),
    protected_worker_id: str | None = None,
) -> WorkerRecoveryBatch:
    """Move recoverable in-flight Runs back to the durable DB queue.

    An interrupted Tool call is never replayed because its external side effect may
    already have happened. Completed Tool results remain untouched and are therefore
    available to the next model Turn through the normal context reconstruction path.
    Approval and user-paused Runs stay parked until their explicit action arrives.
    """

    resumable: list[str] = []
    waiting: list[str] = []
    now = utc_now()
    recovery_statement = (
        select(Run)
        .where(
            or_(
                Run.status == INTERRUPTED,
                (
                    Run.status.in_(
                        ACTIVE_STATUSES - {AWAITING_APPROVAL, AWAITING_INPUT, PAUSED}
                    )
                    & or_(
                        Run.lease_expires_at.is_(None),
                        Run.lease_expires_at <= now,
                    )
                ),
                (
                    Run.status.in_({AWAITING_APPROVAL, AWAITING_INPUT, PAUSED})
                    & Run.worker_id.is_not(None)
                    & or_(
                        Run.lease_expires_at.is_(None),
                        Run.lease_expires_at <= now,
                    )
                ),
            )
        )
        .order_by(Run.queued_at, Run.id)
    )
    if protected_run_ids:
        protected_ids = tuple(dict.fromkeys(protected_run_ids))
        if protected_worker_id is None:
            recovery_statement = recovery_statement.where(Run.id.not_in(protected_ids))
        else:
            recovery_statement = recovery_statement.where(
                ~(
                    Run.id.in_(protected_ids)
                    & (Run.worker_id == protected_worker_id)
                )
            )
    if db.get_bind().dialect.name == "postgresql":
        recovery_statement = recovery_statement.with_for_update(skip_locked=True)
    recovery_candidates = list(db.scalars(recovery_statement))
    for run in recovery_candidates:
        if run.status == INTERRUPTED and not _is_worker_recoverable(run):
            continue
        if run.status in {AWAITING_APPROVAL, AWAITING_INPUT, PAUSED}:
            if run.status == PAUSED:
                detach_paused_run(db, run, reason="worker_recovery")
                if run.snapshot_json.get("resume_requested") is True:
                    queue_paused_run_for_resume(db, run)
                    resumable.append(run.id)
                    continue
            else:
                run.worker_id = None
                run.heartbeat_at = None
                run.lease_expires_at = None
            waiting.append(run.id)
            continue
        _recover_run(db, run)
        resumable.append(run.id)
    return WorkerRecoveryBatch(tuple(resumable), tuple(waiting))


def mark_worker_shutdown_interrupted(db: Session, *, worker_id: str) -> tuple[str, ...]:
    """Record a graceful worker shutdown without discarding resumable state."""

    interrupted: list[str] = []
    active_runs = list(
        db.scalars(
            select(Run)
            .where(
                Run.status.in_(
                    ACTIVE_STATUSES - {AWAITING_APPROVAL, AWAITING_INPUT, PAUSED}
                )
            )
            .order_by(Run.queued_at, Run.id)
        )
    )
    for run in active_runs:
        previous_status = run.status
        snapshot = dict(run.snapshot_json)
        if run.worker_id != worker_id and snapshot.get("workerId") != worker_id:
            continue
        snapshot["workerRecoverable"] = True
        snapshot["workerInterruptedFrom"] = previous_status
        run.snapshot_json = snapshot
        run.status = INTERRUPTED
        run.error_code = "worker_interrupted"
        run.error_message = "Worker가 종료되어 저장된 안전 지점에서 재개를 기다립니다."
        run.finished_at = utc_now()
        append_event(
            db,
            run,
            "run_interrupted",
            {
                "status": INTERRUPTED,
                "previousStatus": previous_status,
                "recoverable": True,
                "finishedAt": run.finished_at,
            },
        )
        interrupted.append(run.id)
    return tuple(interrupted)


def mark_model_turn_inflight(db: Session, run: Run, *, turn_index: int) -> None:
    snapshot = dict(run.snapshot_json)
    snapshot["model_turn_inflight"] = {
        "turnIndex": max(0, turn_index),
        "draftCheckpoint": len(run.assistant_draft),
        "startedAt": utc_now().isoformat(),
    }
    run.snapshot_json = snapshot
    db.flush()


def clear_model_turn_inflight(db: Session, run: Run) -> None:
    if "model_turn_inflight" not in run.snapshot_json:
        return
    snapshot = dict(run.snapshot_json)
    snapshot.pop("model_turn_inflight", None)
    run.snapshot_json = snapshot
    db.flush()


def detach_paused_run(db: Session, run: Run, *, reason: str) -> bool:
    """Release a paused Run's worker ownership after execution reaches a safe boundary."""

    if run.status != PAUSED:
        return False
    snapshot = dict(run.snapshot_json)
    previous_worker_id = run.worker_id
    already_detached = isinstance(snapshot.get("paused_worker_detached"), dict)
    discarded_placeholders = _discard_streaming_tool_placeholders(db, run)
    interrupted_tools = _interrupt_running_tools(db, run)
    changed = bool(
        previous_worker_id is not None
        or not already_detached
        or discarded_placeholders
        or interrupted_tools
    )
    if not changed:
        run.worker_id = None
        run.heartbeat_at = None
        run.lease_expires_at = None
        return False
    snapshot = dict(run.snapshot_json)
    snapshot["paused_worker_detached"] = {
        "detachedAt": utc_now().isoformat(),
        "reason": reason,
        "interruptedToolCount": len(interrupted_tools),
    }
    run.snapshot_json = snapshot
    run.worker_id = None
    run.heartbeat_at = None
    run.lease_expires_at = None
    append_event(
        db,
        run,
        "run_pause_parked",
        {
            "status": PAUSED,
            "reason": reason,
            "interruptedToolCount": len(interrupted_tools),
        },
    )
    db.flush()
    return True


def queue_paused_run_for_resume(db: Session, run: Run) -> bool:
    """Rewind volatile work and move a taskless paused Run to the durable queue."""

    if run.status != PAUSED:
        return False
    detach_paused_run(db, run, reason="resume_requeue")
    resume_plan(db, run, requeue=True)

    snapshot = dict(run.snapshot_json)
    marker = snapshot.pop("model_turn_inflight", None)
    checkpoint = _draft_checkpoint(marker, len(run.assistant_draft))
    draft_was_reset = checkpoint != len(run.assistant_draft)
    run.assistant_draft = run.assistant_draft[:checkpoint]
    usage = dict(run.usage_json)
    if isinstance(marker, dict):
        turn_index = _nonnegative_int(marker.get("turnIndex"))
        usage["model_turns"] = min(
            _nonnegative_int(usage.get("model_turns")), turn_index
        )
    run.usage_json = usage

    previous_status = snapshot.pop("resume_status", None)
    snapshot.pop("resume_requested", None)
    snapshot.pop("resume_requested_at", None)
    snapshot.pop("paused_worker_detached", None)
    draft_revision = _nonnegative_int(
        snapshot.get("assistant_draft_revision")
    )
    if draft_was_reset:
        draft_revision += 1
        snapshot["assistant_draft_revision"] = draft_revision
    run.snapshot_json = snapshot
    run.queued_at = utc_now()
    run.finished_at = None
    run.error_code = None
    run.error_message = None
    transition_run(db, run, QUEUED)
    if draft_was_reset:
        append_event(
            db,
            run,
            "assistant_draft_rewound",
            {
                "messageId": str(run.snapshot_json.get("assistant_message_id", "")),
                "text": run.assistant_draft,
                "retainedCharacters": checkpoint,
                "revision": draft_revision,
            },
        )
    append_event(
        db,
        run,
        "run_resume_recovery_scheduled",
        {
            "status": QUEUED,
            "previousStatus": previous_status,
            "retainedDraftCharacters": checkpoint,
            "draftReset": draft_was_reset,
        },
    )
    db.flush()
    return draft_was_reset


def _discard_streaming_tool_placeholders(db: Session, run: Run) -> int:
    placeholders = list(
        db.scalars(
            select(ToolExecution).where(
                ToolExecution.run_id == run.id,
                ToolExecution.status == "streaming",
            )
        )
    )
    for tool in placeholders:
        db.delete(tool)
    if placeholders:
        append_event(
            db,
            run,
            "provider_partial_tool_calls_discarded",
            {"toolCallCount": len(placeholders), "toolNames": []},
        )
    return len(placeholders)


def _interrupt_running_tools(db: Session, run: Run) -> list[ToolExecution]:
    interrupted_tools = list(
        db.scalars(
            select(ToolExecution).where(
                ToolExecution.run_id == run.id,
                ToolExecution.status == "running",
            )
        )
    )
    for tool in interrupted_tools:
        tool.status = "failed"
        tool.error_code = "worker_restarted_unknown_outcome"
        tool.error_message = (
            "Worker가 재시작되어 이전 Tool 실행 결과를 확정할 수 없습니다. "
            "중복 부작용을 막기 위해 자동 재실행하지 않았습니다."
        )
        tool.finished_at = utc_now()
        finish_tool_subtask(db, tool)
        append_event(
            db,
            run,
            "tool_completed",
            {
                "execution": {
                    "id": tool.id,
                    "toolCallId": tool.tool_call_id,
                    "toolName": tool.tool_name,
                    "status": tool.status,
                    "errorCode": tool.error_code,
                    "completedAt": tool.finished_at,
                }
            },
        )
    return interrupted_tools


def _recover_run(db: Session, run: Run) -> None:
    previous_status = run.status
    snapshot = dict(run.snapshot_json)
    snapshot.pop("workerRecoverable", None)
    snapshot.pop("workerInterruptedFrom", None)
    if previous_status != INTERRUPTED:
        append_event(
            db,
            run,
            "run_interrupted",
            {
                "status": INTERRUPTED,
                "previousStatus": previous_status,
                "recoverable": True,
                "finishedAt": utc_now(),
            },
        )
    marker = snapshot.pop("model_turn_inflight", None)
    checkpoint = _draft_checkpoint(marker, len(run.assistant_draft))
    if marker is None and not isinstance(snapshot.get("tool_checkpoint"), dict):
        # Legacy in-flight Runs have no safe boundary for partial model text.
        checkpoint = 0
    draft_was_reset = checkpoint != len(run.assistant_draft)
    run.assistant_draft = run.assistant_draft[:checkpoint]

    usage = dict(run.usage_json)
    if isinstance(marker, dict):
        turn_index = _nonnegative_int(marker.get("turnIndex"))
        usage["model_turns"] = min(
            _nonnegative_int(usage.get("model_turns")), turn_index
        )
    run.usage_json = usage

    interrupted_tools = _interrupt_running_tools(db, run)

    _fail_unstarted_subtasks(db, run)
    _queue_active_plan_steps(db, run)

    recovery_count = _nonnegative_int(snapshot.get("workerRecoveryCount")) + 1
    snapshot["workerRecoveryCount"] = recovery_count
    snapshot["workerRecovery"] = {
        "previousStatus": previous_status,
        "recoveredAt": utc_now().isoformat(),
        "interruptedToolCount": len(interrupted_tools),
        "draftReset": draft_was_reset,
    }
    draft_revision = _nonnegative_int(
        snapshot.get("assistant_draft_revision")
    )
    if draft_was_reset:
        draft_revision += 1
        snapshot["assistant_draft_revision"] = draft_revision
    run.snapshot_json = snapshot
    run.worker_id = None
    run.heartbeat_at = None
    run.lease_expires_at = None
    run.status = QUEUED
    run.finished_at = None
    run.error_code = None
    run.error_message = None
    current_plan = plan_snapshot(db, run)
    if current_plan is not None:
        run.snapshot_json = {
            **run.snapshot_json,
            "plan": jsonable_encoder(current_plan),
        }
    if draft_was_reset:
        append_event(
            db,
            run,
            "assistant_draft_rewound",
            {
                "messageId": str(run.snapshot_json.get("assistant_message_id", "")),
                "text": run.assistant_draft,
                "retainedCharacters": checkpoint,
                "revision": draft_revision,
            },
        )
    append_event(
        db,
        run,
        "run_recovery_scheduled",
        {
            "status": QUEUED,
            "previousStatus": previous_status,
            "recoveryCount": recovery_count,
            "interruptedToolCount": len(interrupted_tools),
            "retainedDraftCharacters": checkpoint,
        },
    )


def _fail_unstarted_subtasks(db: Session, run: Run) -> None:
    subtasks = list(
        db.scalars(
            select(PlanSubtask)
            .join(PlanStep, PlanStep.id == PlanSubtask.plan_step_id)
            .join(Plan, Plan.id == PlanStep.plan_id)
            .where(
                Plan.run_id == run.id,
                PlanSubtask.status.in_(("queued", "running")),
            )
        )
    )
    for subtask in subtasks:
        if subtask.tool_execution_id is not None and subtask.status == "failed":
            continue
        subtask.status = "failed"
        subtask.completed_at = utc_now()
        subtask.error_code = "worker_restarted_before_execution"
        subtask.error_message = (
            "Worker 재시작 전에 실행 결과가 저장되지 않아 자동 재실행하지 않았습니다."
        )


def _queue_active_plan_steps(db: Session, run: Run) -> None:
    plan = db.scalar(select(Plan).where(Plan.run_id == run.id))
    if plan is None:
        return
    for step in db.scalars(select(PlanStep).where(PlanStep.plan_id == plan.id)):
        if step.status in {"running", "blocked"}:
            step.status = "queued"
            step.completed_at = None
            step.error_code = None
            step.error_message = None
    plan.status = "active"
    plan.updated_at = utc_now()


def _draft_checkpoint(marker: Any, draft_length: int) -> int:
    if not isinstance(marker, dict):
        return draft_length
    return min(_nonnegative_int(marker.get("draftCheckpoint")), draft_length)


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _is_worker_recoverable(run: Run) -> bool:
    return bool(
        run.snapshot_json.get("workerRecoverable")
        or run.error_code == "worker_interrupted"
    )


__all__ = [
    "WorkerRecoveryBatch",
    "clear_model_turn_inflight",
    "detach_paused_run",
    "mark_worker_shutdown_interrupted",
    "mark_model_turn_inflight",
    "prepare_worker_recovery",
    "queue_paused_run_for_resume",
]
