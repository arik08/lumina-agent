from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .audit import redact_metadata


_SENSITIVE_PATH_PREFIXES = (
    "/api/conversation-shares/",
    "/shared/",
)


def request_log_path(path: str, *, route_template: str | None = None) -> str:
    """Return a low-cardinality path that never exposes share tokens."""

    if route_template:
        return route_template
    for prefix in _SENSITIVE_PATH_PREFIXES:
        if path.startswith(prefix):
            suffix = path[len(prefix) :]
            _, separator, remainder = suffix.partition("/")
            return f"{prefix}[REDACTED]{separator}{remainder}" if suffix else prefix
    return path


def structured_event(event: str, /, **fields: Any) -> str:
    """Serialize one redacted JSON log event.

    Callers deliberately pass an allowlisted set of operational fields.  The
    recursive redaction is a second line of defence for future fields; request
    bodies, query strings, cookies and authorization headers must never be
    passed here.
    """

    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event,
        **redact_metadata(fields),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def emit_llm_activity(
    state: str,
    *,
    user_login_id: str,
    occurred_at: datetime | None = None,
) -> str:
    """Write one content-free LLM activity line for local usage monitoring."""

    timestamp = occurred_at or datetime.now().astimezone()
    line = (
        f"({timestamp:%H:%M:%S}) [Lumina] LLM response {state} "
        f"user={user_login_id}"
    )
    print(line, flush=True)
    return line


__all__ = ["emit_llm_activity", "request_log_path", "structured_event"]
