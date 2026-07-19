from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..models import User, utc_now
from .models import (
    DeepAnalysisCommand,
    DeepAnalysisEvent,
    DeepAnalysisMission,
)


_FORBIDDEN_PAYLOAD_KEYS = {
    "answer_text",
    "content",
    "input",
    "objective",
    "output",
    "prompt",
    "raw",
    "secret",
    "text",
    "token",
}

def _safe_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe_payload(item)
            for key, item in value.items()
            if str(key).lower() not in _FORBIDDEN_PAYLOAD_KEYS
        }
    if isinstance(value, list):
        return [_safe_payload(item) for item in value[:200]]
    if isinstance(value, str):
        return value[:500]
    return value


def request_digest(payload: Any) -> str:
    encoded = json.dumps(
        jsonable_encoder(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def claim_command(
    db: Session,
    *,
    mission: DeepAnalysisMission,
    user: User,
    command_type: str,
    idempotency_key: str | None,
    payload: Any,
) -> tuple[DeepAnalysisCommand | None, bool]:
    if not idempotency_key:
        return None, True
    key = idempotency_key.strip()
    if not key or len(key) > 160:
        raise ApiProblem(400, "invalid_idempotency_key", "Idempotency-Key는 160자 이하여야 합니다.")
    digest = request_digest(payload)
    existing = db.scalar(
        select(DeepAnalysisCommand).where(
            DeepAnalysisCommand.mission_id == mission.id,
            DeepAnalysisCommand.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.command_type != command_type or existing.request_digest != digest:
            raise ApiProblem(
                409,
                "idempotency_conflict",
                "같은 Idempotency-Key가 다른 요청에 이미 사용되었습니다.",
            )
        return existing, False
    command = DeepAnalysisCommand(
        mission_id=mission.id,
        actor_user_id=user.id,
        command_type=command_type,
        idempotency_key=key,
        request_digest=digest,
        status="pending",
        result_json={},
        created_at=utc_now(),
    )
    db.add(command)
    db.flush()
    return command, True


def complete_command(
    db: Session,
    command: DeepAnalysisCommand | None,
    *,
    result: dict[str, Any] | None = None,
) -> None:
    if command is None:
        return
    command.status = "applied"
    command.result_json = jsonable_encoder(result or {})
    command.applied_at = utc_now()
    db.flush()


def emit_event(
    db: Session,
    mission: DeepAnalysisMission,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    actor_user_id: str | None = None,
) -> DeepAnalysisEvent:
    sequence = db.scalar(
        update(DeepAnalysisMission)
        .where(DeepAnalysisMission.id == mission.id)
        .values(event_sequence=DeepAnalysisMission.event_sequence + 1)
        .returning(DeepAnalysisMission.event_sequence)
    )
    if sequence is None:
        raise RuntimeError("Deep-analysis Mission event sequence allocation failed")
    event = DeepAnalysisEvent(
        mission_id=mission.id,
        sequence=int(sequence),
        event_type=event_type[:80],
        actor_user_id=actor_user_id,
        payload_json=jsonable_encoder(_safe_payload(payload or {})),
        created_at=utc_now(),
    )
    db.add(event)
    db.flush()
    db.expire(mission, ["event_sequence"])
    return event


def list_events(
    db: Session,
    mission_id: str,
    *,
    after_sequence: int = 0,
) -> list[DeepAnalysisEvent]:
    return list(
        db.scalars(
            select(DeepAnalysisEvent)
            .where(
                DeepAnalysisEvent.mission_id == mission_id,
                DeepAnalysisEvent.sequence > max(0, after_sequence),
            )
            .order_by(DeepAnalysisEvent.sequence)
        )
    )


def event_payload(event: DeepAnalysisEvent) -> dict[str, Any]:
    return {
        "mission_id": event.mission_id,
        "sequence": event.sequence,
        "type": event.event_type,
        "payload": event.payload_json,
        "created_at": event.created_at,
    }
