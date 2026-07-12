from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import AuditEvent, User


_REDACTED_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "token_hash",
        "access_token",
        "refresh_token",
        "session_token",
        "csrf_token",
        "url_token",
        "authorization",
        "api_key",
        "apikey",
        "pgpt_api_key",
        "secret",
        "secret_ref",
        "credential",
        "employee_no",
        "system_code",
        "systemcode",
        "company_code",
        "companycode",
        "cookie",
    }
)


def redact_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if key.lower() in _REDACTED_KEYS
            else redact_metadata(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [redact_metadata(item) for item in value]
    return value


def record_audit(
    db: Session,
    *,
    action: str,
    target_type: str,
    result: str,
    actor: User | None = None,
    target_id: str | None = None,
    request_id: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        organization_id=actor.organization_id if actor else None,
        actor_user_id=actor.id if actor else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        request_id=request_id,
        reason=reason,
        metadata_json=redact_metadata(metadata or {}),
    )
    db.add(event)
    return event
