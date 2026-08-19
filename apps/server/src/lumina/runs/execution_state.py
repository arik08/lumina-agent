from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


MODEL_TURN_INFLIGHT_KEY = "model_turn_inflight"
TOOL_CHECKPOINT_KEY = "tool_checkpoint"

ExecutionPhase = Literal[
    "model_turn_inflight",
    "tool_checkpoint",
    "untracked",
]


@dataclass(frozen=True, slots=True)
class ModelTurnPosition:
    turn_index: int
    draft_checkpoint: int


@dataclass(frozen=True, slots=True)
class ExecutionRecoveryStateV1:
    """Typed projection of the durable snapshot fields used during recovery.

    The existing snapshot keys remain the storage contract for compatibility. This
    projection gives recovery code one total program-counter view while old rows and
    in-flight Runs continue to work without a data migration.
    """

    phase: ExecutionPhase
    model_turn: ModelTurnPosition | None
    has_tool_checkpoint: bool
    tool_checkpoint_kind: str | None
    tool_checkpoint_version: int | None
    schema_version: int = 1

    def retained_draft_length(
        self,
        draft_length: int,
        *,
        preserve_untracked: bool,
    ) -> int:
        bounded_length = max(0, draft_length)
        if self.model_turn is not None:
            return min(self.model_turn.draft_checkpoint, bounded_length)
        if self.has_tool_checkpoint or preserve_untracked:
            return bounded_length
        return 0


def execution_recovery_state(
    snapshot: Mapping[str, Any],
) -> ExecutionRecoveryStateV1:
    marker = snapshot.get(MODEL_TURN_INFLIGHT_KEY)
    checkpoint_mapping = read_tool_checkpoint(snapshot)
    has_tool_checkpoint = checkpoint_mapping is not None
    checkpoint_kind = (
        str(checkpoint_mapping.get("kind", "")).strip() or None
        if checkpoint_mapping is not None
        else None
    )
    checkpoint_version = (
        _optional_nonnegative_int(checkpoint_mapping.get("version"))
        if checkpoint_mapping is not None
        else None
    )

    if isinstance(marker, Mapping):
        return ExecutionRecoveryStateV1(
            phase="model_turn_inflight",
            model_turn=ModelTurnPosition(
                turn_index=_nonnegative_int(marker.get("turnIndex")),
                draft_checkpoint=_nonnegative_int(marker.get("draftCheckpoint")),
            ),
            has_tool_checkpoint=has_tool_checkpoint,
            tool_checkpoint_kind=checkpoint_kind,
            tool_checkpoint_version=checkpoint_version,
        )
    if has_tool_checkpoint:
        return ExecutionRecoveryStateV1(
            phase="tool_checkpoint",
            model_turn=None,
            has_tool_checkpoint=True,
            tool_checkpoint_kind=checkpoint_kind,
            tool_checkpoint_version=checkpoint_version,
        )
    return ExecutionRecoveryStateV1(
        phase="untracked",
        model_turn=None,
        has_tool_checkpoint=False,
        tool_checkpoint_kind=None,
        tool_checkpoint_version=None,
    )


def read_tool_checkpoint(snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
    checkpoint = snapshot.get(TOOL_CHECKPOINT_KEY)
    return dict(checkpoint) if isinstance(checkpoint, Mapping) else None


def with_model_turn_inflight(
    snapshot: Mapping[str, Any],
    *,
    turn_index: int,
    draft_checkpoint: int,
    started_at: str,
) -> dict[str, Any]:
    updated = dict(snapshot)
    updated[MODEL_TURN_INFLIGHT_KEY] = {
        "turnIndex": max(0, turn_index),
        "draftCheckpoint": max(0, draft_checkpoint),
        "startedAt": started_at,
    }
    return updated


def without_model_turn_inflight(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(snapshot)
    updated.pop(MODEL_TURN_INFLIGHT_KEY, None)
    return updated


def with_updated_model_turn_position(
    snapshot: Mapping[str, Any],
    *,
    turn_index: int,
    draft_checkpoint: int,
    safe_boundary_at: str,
) -> dict[str, Any]:
    updated = dict(snapshot)
    marker = updated.get(MODEL_TURN_INFLIGHT_KEY)
    if not isinstance(marker, Mapping):
        return updated
    updated[MODEL_TURN_INFLIGHT_KEY] = {
        **marker,
        "turnIndex": max(0, turn_index),
        "draftCheckpoint": max(0, draft_checkpoint),
        "safeBoundaryAt": safe_boundary_at,
    }
    return updated


def with_tool_checkpoint(
    snapshot: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    *,
    clear_model_turn: bool = False,
) -> dict[str, Any]:
    updated = dict(snapshot)
    if clear_model_turn:
        updated.pop(MODEL_TURN_INFLIGHT_KEY, None)
    updated[TOOL_CHECKPOINT_KEY] = dict(checkpoint)
    return updated


def without_tool_checkpoint(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(snapshot)
    updated.pop(TOOL_CHECKPOINT_KEY, None)
    return updated


def without_execution_checkpoints(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(snapshot)
    updated.pop(MODEL_TURN_INFLIGHT_KEY, None)
    updated.pop(TOOL_CHECKPOINT_KEY, None)
    return updated


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "ExecutionRecoveryStateV1",
    "ModelTurnPosition",
    "execution_recovery_state",
    "read_tool_checkpoint",
    "with_model_turn_inflight",
    "with_tool_checkpoint",
    "with_updated_model_turn_position",
    "without_execution_checkpoints",
    "without_model_turn_inflight",
    "without_tool_checkpoint",
]
