from __future__ import annotations

import json

from datetime import datetime

from lumina.observability import emit_llm_activity, request_log_path, structured_event


def test_structured_event_is_json_and_redacts_known_secret_fields() -> None:
    event = json.loads(
        structured_event(
            "test_event",
            request_id="request-1",
            method="GET",
            path="/api/health/live",
            status_code=200,
            nested={
                "authorization": "Bearer should-not-leak",
                "secret_ref": "vault://must-not-leak",
            },
        )
    )

    assert event["event"] == "test_event"
    assert event["request_id"] == "request-1"
    assert event["path"] == "/api/health/live"
    assert event["nested"]["authorization"] == "[REDACTED]"
    assert event["nested"]["secret_ref"] == "[REDACTED]"
    assert "should-not-leak" not in json.dumps(event)


def test_request_log_path_prefers_template_and_redacts_share_tokens() -> None:
    secret = "opaque-share-token-that-must-not-appear"

    assert (
        request_log_path(
            f"/api/conversation-shares/{secret}/artifacts/artifact-1/download",
            route_template=(
                "/api/conversation-shares/{token}/artifacts/{artifact_id}/download"
            ),
        )
        == "/api/conversation-shares/{token}/artifacts/{artifact_id}/download"
    )
    fallback = request_log_path(f"/shared/{secret}/unknown")
    assert fallback == "/shared/[REDACTED]/unknown"
    assert secret not in fallback


def test_emit_llm_activity_writes_one_content_free_line(capsys) -> None:
    line = emit_llm_activity(
        "completed",
        user_login_id="admin@posco.com",
        occurred_at=datetime(2026, 7, 12, 14, 32, 8),
    )

    assert line == (
        "(14:32:08) [Lumina] LLM response completed "
        "user=admin@posco.com"
    )
    assert capsys.readouterr().out == f"{line}\n"
