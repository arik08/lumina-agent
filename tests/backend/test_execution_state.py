from __future__ import annotations

from lumina.runs.execution_state import (
    execution_recovery_state,
    read_tool_checkpoint,
    with_model_turn_inflight,
    with_tool_checkpoint,
    with_updated_model_turn_position,
    without_execution_checkpoints,
    without_model_turn_inflight,
    without_tool_checkpoint,
)


def test_model_turn_is_the_current_position_over_an_older_tool_checkpoint() -> None:
    state = execution_recovery_state(
        {
            "model_turn_inflight": {
                "turnIndex": 3,
                "draftCheckpoint": 7,
            },
            "tool_checkpoint": {
                "version": 2,
                "kind": "completed_tools",
            },
        }
    )

    assert state.schema_version == 1
    assert state.phase == "model_turn_inflight"
    assert state.model_turn is not None
    assert state.model_turn.turn_index == 3
    assert state.has_tool_checkpoint is True
    assert state.tool_checkpoint_kind == "completed_tools"
    assert state.retained_draft_length(20, preserve_untracked=False) == 7


def test_tool_checkpoint_is_a_safe_recovery_position() -> None:
    snapshot = {"tool_checkpoint": {"version": "2", "kind": "approval"}}
    state = execution_recovery_state(snapshot)

    assert state.phase == "tool_checkpoint"
    assert state.model_turn is None
    assert state.tool_checkpoint_version == 2
    assert state.retained_draft_length(11, preserve_untracked=False) == 11
    checkpoint = read_tool_checkpoint(snapshot)
    assert checkpoint == {"version": "2", "kind": "approval"}
    assert checkpoint is not snapshot["tool_checkpoint"]


def test_malformed_tool_checkpoint_is_not_a_recovery_position() -> None:
    snapshot = {"tool_checkpoint": "not-a-mapping"}

    assert read_tool_checkpoint(snapshot) is None
    assert execution_recovery_state(snapshot).phase == "untracked"


def test_untracked_position_keeps_legacy_recovery_policy_explicit() -> None:
    state = execution_recovery_state({"unrelated": True})

    assert state.phase == "untracked"
    assert state.retained_draft_length(9, preserve_untracked=True) == 9
    assert state.retained_draft_length(9, preserve_untracked=False) == 0


def test_snapshot_updates_preserve_unrelated_state_and_do_not_mutate_input() -> None:
    original = {"projectId": "project-1"}
    inflight = with_model_turn_inflight(
        original,
        turn_index=-2,
        draft_checkpoint=5,
        started_at="2026-08-19T00:00:00+00:00",
    )

    assert original == {"projectId": "project-1"}
    assert inflight["projectId"] == "project-1"
    assert inflight["model_turn_inflight"]["turnIndex"] == 0

    checkpoint = {"version": 2, "kind": "pending_tools"}
    stored = with_tool_checkpoint(
        inflight,
        checkpoint,
        clear_model_turn=True,
    )
    checkpoint["kind"] = "changed-after-store"

    assert "model_turn_inflight" not in stored
    assert stored["tool_checkpoint"]["kind"] == "pending_tools"
    assert without_model_turn_inflight(inflight) == original
    assert without_tool_checkpoint(stored) == original
    assert without_execution_checkpoints(stored) == original


def test_safe_boundary_update_preserves_model_turn_metadata() -> None:
    inflight = with_model_turn_inflight(
        {},
        turn_index=1,
        draft_checkpoint=2,
        started_at="started",
    )

    updated = with_updated_model_turn_position(
        inflight,
        turn_index=4,
        draft_checkpoint=8,
        safe_boundary_at="safe",
    )

    assert updated["model_turn_inflight"] == {
        "turnIndex": 4,
        "draftCheckpoint": 8,
        "startedAt": "started",
        "safeBoundaryAt": "safe",
    }
