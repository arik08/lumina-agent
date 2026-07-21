from __future__ import annotations

from collections.abc import Mapping


QUEUED = "queued"
PREPARING = "preparing"
MODEL_STREAMING = "model_streaming"
AWAITING_APPROVAL = "awaiting_approval"
AWAITING_INPUT = "awaiting_input"
TOOLS_RUNNING = "tools_running"
PAUSED = "paused"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
LIMIT_REACHED = "limit_reached"
INTERRUPTED = "interrupted"

TERMINAL_STATUSES = frozenset(
    {COMPLETED, FAILED, CANCELLED, LIMIT_REACHED, INTERRUPTED}
)
ACTIVE_STATUSES = frozenset(
    {PREPARING, MODEL_STREAMING, AWAITING_APPROVAL, AWAITING_INPUT, TOOLS_RUNNING, PAUSED}
)
# Approval and input waits release their executor task; paused Runs retain it until resume.
EXECUTION_SLOT_STATUSES = ACTIVE_STATUSES - {AWAITING_APPROVAL, AWAITING_INPUT}

ALLOWED_TRANSITIONS: Mapping[str, frozenset[str]] = {
    QUEUED: frozenset({PREPARING, TOOLS_RUNNING, PAUSED, FAILED, CANCELLED}),
    PREPARING: frozenset(
        {MODEL_STREAMING, FAILED, CANCELLED, LIMIT_REACHED, INTERRUPTED}
    ),
    MODEL_STREAMING: frozenset(
        {
            AWAITING_APPROVAL,
            AWAITING_INPUT,
            TOOLS_RUNNING,
            PAUSED,
            COMPLETED,
            FAILED,
            CANCELLED,
            LIMIT_REACHED,
            INTERRUPTED,
        }
    ),
    AWAITING_APPROVAL: frozenset(
        {QUEUED, TOOLS_RUNNING, FAILED, CANCELLED, LIMIT_REACHED, INTERRUPTED}
    ),
    AWAITING_INPUT: frozenset(
        {QUEUED, FAILED, CANCELLED, LIMIT_REACHED, INTERRUPTED}
    ),
    TOOLS_RUNNING: frozenset(
        {
            MODEL_STREAMING,
            PAUSED,
            FAILED,
            CANCELLED,
            LIMIT_REACHED,
            INTERRUPTED,
        }
    ),
    PAUSED: frozenset(
        {QUEUED, PREPARING, MODEL_STREAMING, TOOLS_RUNNING, CANCELLED, LIMIT_REACHED}
    ),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
    LIMIT_REACHED: frozenset(),
    INTERRUPTED: frozenset({PREPARING, CANCELLED}),
}


class InvalidRunTransition(ValueError):
    pass


def ensure_transition(current: str, target: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current)
    if allowed is None:
        raise InvalidRunTransition(f"Unknown run status: {current}")
    if target not in allowed:
        raise InvalidRunTransition(f"Run cannot transition from {current} to {target}")


def sidebar_status(status: str) -> str:
    if status == AWAITING_APPROVAL:
        return "approval"
    if status == AWAITING_INPUT:
        return "input"
    if status in ACTIVE_STATUSES:
        return "running"
    return status
