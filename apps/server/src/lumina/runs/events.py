from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from ..models import Run, RunEvent

def append_event(
    db: Session, run: Run, event_type: str, payload: dict[str, Any]
) -> RunEvent:
    run.last_sequence += 1
    event = RunEvent(
        run_id=run.id,
        conversation_id=run.conversation_id,
        sequence=run.last_sequence,
        event_type=event_type,
        payload_json=jsonable_encoder(payload),
    )
    db.add(event)
    db.flush()
    return event
