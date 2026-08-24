from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ..models import Run
from .state import EXECUTION_SLOT_STATUSES


_ACTIVE_ELAPSED_SECONDS = "active_elapsed_seconds"
_ACTIVE_ELAPSED_STARTED_AT = "active_elapsed_started_at"


def run_active_elapsed_seconds(run: Run, *, now: datetime) -> float:
    """Return persisted execution time without user-controlled wait periods."""
    snapshot = run.snapshot_json if isinstance(run.snapshot_json, Mapping) else {}
    has_persisted_timing = _ACTIVE_ELAPSED_SECONDS in snapshot
    elapsed = _nonnegative_float(snapshot.get(_ACTIVE_ELAPSED_SECONDS))
    active_started_at = _parse_datetime(snapshot.get(_ACTIVE_ELAPSED_STARTED_AT))
    if run.status in EXECUTION_SLOT_STATUSES and active_started_at is not None:
        elapsed += max(0.0, (now - active_started_at).total_seconds())
    elif (
        run.status in EXECUTION_SLOT_STATUSES
        and not has_persisted_timing
        and run.started_at is not None
    ):
        # Preserve the safety limit for a legacy Run that was already executing
        # when active-time accounting was introduced. Waiting legacy Runs start a
        # fresh measured segment when they are resumed.
        elapsed = max(0.0, (now - _as_utc(run.started_at)).total_seconds())
    return elapsed


def update_run_active_timing(
    run: Run,
    *,
    current_status: str,
    target_status: str,
    now: datetime,
) -> None:
    """Persist completed active segments and start the next one when applicable."""
    snapshot = dict(run.snapshot_json)
    elapsed = _nonnegative_float(snapshot.get(_ACTIVE_ELAPSED_SECONDS))
    active_started_at = _parse_datetime(snapshot.get(_ACTIVE_ELAPSED_STARTED_AT))
    if current_status in EXECUTION_SLOT_STATUSES and active_started_at is not None:
        elapsed += max(0.0, (now - active_started_at).total_seconds())

    snapshot[_ACTIVE_ELAPSED_SECONDS] = elapsed
    if target_status in EXECUTION_SLOT_STATUSES:
        snapshot[_ACTIVE_ELAPSED_STARTED_AT] = _as_utc(now).isoformat()
    else:
        snapshot.pop(_ACTIVE_ELAPSED_STARTED_AT, None)
    run.snapshot_json = snapshot


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _nonnegative_float(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = float(value)
        if converted >= 0:
            return converted
    return 0.0


__all__ = ["run_active_elapsed_seconds", "update_run_active_timing"]
