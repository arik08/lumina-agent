import pytest

from lumina.runs.state import (
    CANCELLED,
    COMPLETED,
    MODEL_STREAMING,
    PREPARING,
    QUEUED,
    InvalidRunTransition,
    ensure_transition,
    sidebar_status,
)


def test_run_state_accepts_documented_path() -> None:
    ensure_transition(QUEUED, PREPARING)
    ensure_transition(PREPARING, MODEL_STREAMING)
    ensure_transition(MODEL_STREAMING, COMPLETED)


def test_terminal_run_cannot_be_restarted_silently() -> None:
    with pytest.raises(InvalidRunTransition):
        ensure_transition(COMPLETED, PREPARING)


def test_cancelled_sidebar_state_remains_cancelled() -> None:
    assert sidebar_status(CANCELLED) == CANCELLED
    assert sidebar_status(MODEL_STREAMING) == "running"
