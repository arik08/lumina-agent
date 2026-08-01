from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Run, RunEvent, utc_now
from ..notifications import create_run_transition_notification
from .events import append_event
from .state import COMPLETED, PREPARING, TERMINAL_STATUSES, ensure_transition


def transition_run(
    db: Session, run: Run, target: str, *, event_type: str = "run_status_changed"
) -> RunEvent:
    ensure_transition(run.status, target)
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
    run.status = target
    now = utc_now()
    if target == PREPARING and run.started_at is None:
        run.started_at = now
    if target in TERMINAL_STATUSES:
        run.finished_at = now
        run.snapshot_json = {**run.snapshot_json, "artifact_progress": None}
    event = append_event(
        db, run, event_type, {"status": target, "finishedAt": run.finished_at}
    )
    create_run_transition_notification(db, run, target)
    return event
