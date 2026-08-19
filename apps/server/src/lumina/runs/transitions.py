from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from ..models import Run, RunEvent, utc_now
from ..notifications import create_run_transition_notification
from .events import append_event
from .state import COMPLETED, PREPARING, TERMINAL_STATUSES, ensure_transition


class StaleRunTransition(RuntimeError):
    pass


def transition_run(
    db: Session,
    run: Run,
    target: str,
    *,
    event_type: str = "run_status_changed",
    event_payload: Mapping[str, Any] | None = None,
) -> RunEvent:
    current = run.status
    ensure_transition(current, target)
    _compare_and_set_status(db, run, current=current, target=target)
    if target == COMPLETED:
        work_plan = run.snapshot_json.get("work_plan", [])
        if isinstance(work_plan, list) and any(
            isinstance(item, dict) and item.get("status") != "completed"
            for item in work_plan
        ):
            completed_work_plan = [
                {**item, "status": "completed"} if isinstance(item, dict) else item
                for item in work_plan
            ]
            run.snapshot_json = {
                **run.snapshot_json,
                "work_plan": completed_work_plan,
            }
            append_event(
                db,
                run,
                "work_plan_updated",
                {"steps": completed_work_plan},
            )
    now = utc_now()
    if target == PREPARING and run.started_at is None:
        run.started_at = now
    if target in TERMINAL_STATUSES:
        run.finished_at = now
        run.snapshot_json = {**run.snapshot_json, "artifact_progress": None}
    event = append_event(
        db,
        run,
        event_type,
        {
            **dict(event_payload or {}),
            "status": target,
            "finishedAt": run.finished_at,
        },
    )
    create_run_transition_notification(db, run, target)
    return event


def _compare_and_set_status(
    db: Session,
    run: Run,
    *,
    current: str,
    target: str,
) -> None:
    db.flush()
    result = cast(
        CursorResult[Any],
        db.execute(
            update(Run)
            .where(Run.id == run.id, Run.status == current)
            .values(status=target)
            .execution_options(synchronize_session=False)
        ),
    )
    if result.rowcount != 1:
        actual = db.scalar(select(Run.status).where(Run.id == run.id))
        if actual is not None:
            set_committed_value(run, "status", actual)
        raise StaleRunTransition(
            f"Run {run.id} status changed concurrently: expected {current}, "
            f"found {actual or 'missing'}, target {target}"
        )
    set_committed_value(run, "status", target)


__all__ = ["StaleRunTransition", "transition_run"]
