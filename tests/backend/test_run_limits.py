from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.agent.executor import (
    _usage_payload,
    local_run_executor,
)
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Run, RunEvent
from lumina.providers import (
    MockProvider,
    ProviderCapabilities,
    ProviderEvent,
    ProviderRequest,
    ProviderUsage,
)
from lumina.providers.catalog import initial_model_catalog, model_operational_profile
from lumina.runs.service import _usage_snapshot
from lumina.runs.state import TERMINAL_STATUSES


def test_usage_payload_estimates_codex_gpt_5_4_cost() -> None:
    payload = _usage_payload(
        ProviderUsage(
            input_tokens=20_053,
            cached_input_tokens=8_526,
            uncached_input_tokens=11_527,
            output_tokens=2_335,
        ),
        provider_id="codex",
        model="gpt-5.4",
    )

    assert payload["cost_usd"] == pytest.approx(0.065974)
    assert payload["estimated_cost_breakdown_usd"] == pytest.approx(
        {
            "uncached_input": 0.0288175,
            "cached_input": 0.0021315,
            "cache_write_input": 0.0,
            "input": 0.030949,
            "output": 0.035025,
            "total": 0.065974,
        }
    )
    assert payload["cost_basis"] == "price_table_estimate"
    assert payload["pricing_version"] == "public-list-2026-07-12"


def test_usage_payload_prefers_provider_reported_cost() -> None:
    payload = _usage_payload(
        ProviderUsage(
            input_tokens=20_053,
            output_tokens=2_335,
            raw={"cost_usd": 0.1234},
        ),
        provider_id="codex",
        model="gpt-5.6-terra",
    )

    assert payload["cost_usd"] == pytest.approx(0.1234)
    assert payload["cost_basis"] == "provider_reported"
    assert "pricing_version" not in payload


def test_usage_payload_labels_subscription_cost_as_management_estimate() -> None:
    payload = _usage_payload(
        ProviderUsage(
            input_tokens=20_053,
            output_tokens=2_335,
            raw={"auth_mode": "chatgpt", "billing": "subscription_usage"},
        ),
        provider_id="codex",
        model="gpt-5.5",
    )

    assert payload["cost_basis"] == "subscription_price_table_estimate"
    assert payload["cost_usd"] > 0
    assert payload["pricing_version"] == "public-list-2026-07-12"


def test_usage_snapshot_backfills_cost_breakdown_for_existing_runs() -> None:
    run = type(
        "StoredRun",
        (),
        {
            "provider_id": "codex",
            "model_key": "gpt-5.4",
            "usage_json": {
                "input_tokens": 20_053,
                "cached_input_tokens": 8_526,
                "output_tokens": 2_335,
                "cost_usd": 0.065974,
            },
        },
    )()

    usage = _usage_snapshot(run)

    assert usage["cost_usd"] == pytest.approx(0.065974)
    assert usage["estimated_cost_breakdown_usd"]["total"] == pytest.approx(0.065974)


@pytest.mark.parametrize(
    ("provider_id", "model", "expected_cost"),
    [
        ("pgpt", "gpt-5.6-terra", 1.4),
        ("pgpt", "gpt-5.6-luna", 0.14),
        ("codex", "gpt-5.5", 3.5),
        ("codex", "gpt-5.4", 1.75),
        ("openai", "gpt-5.6-sol", 3.5),
        ("openai", "gpt-5.6-terra", 1.4),
        ("openai", "gpt-5.6-luna", 0.14),
        ("anthropic", "claude-opus-4-8", 3.0),
        ("anthropic", "claude-sonnet-5", 1.2),
        ("anthropic", "claude-haiku-4-5", 0.6),
        ("google", "gemini-3.1-pro", 1.4),
        ("google", "gemini-3.5-flash", 1.05),
    ],
)
def test_usage_payload_estimates_every_public_catalog_model(
    provider_id: str, model: str, expected_cost: float
) -> None:
    payload = _usage_payload(
        ProviderUsage(input_tokens=100_000, output_tokens=100_000),
        provider_id=provider_id,
        model=model,
    )

    assert payload["cost_usd"] == pytest.approx(expected_cost)


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5.6-terra", (2.0, 0.2, 2.5, 12.0, 4.0, 0.4, 5.0, 18.0)),
        ("gpt-5.6-luna", (0.2, 0.02, 0.25, 1.2, 0.4, 0.04, 0.5, 1.8)),
    ],
)
def test_pgpt_gpt_5_6_pricing_matches_public_rate_card(
    model: str, expected: tuple[float, ...]
) -> None:
    profile = model_operational_profile("pgpt", model)
    assert profile is not None
    pricing = profile.token_pricing
    assert pricing is not None
    assert (
        pricing.input,
        pricing.cached_input,
        pricing.cache_write_input,
        pricing.output,
        pricing.long_context_input,
        pricing.long_context_cached_input,
        pricing.long_context_cache_write_input,
        pricing.long_context_output,
    ) == expected
    assert pricing.version == "public-list-2026-08-06"


@pytest.mark.parametrize("provider_id", ["pgpt", "openai_compatible"])
def test_usage_payload_does_not_guess_private_provider_pricing(
    provider_id: str,
) -> None:
    payload = _usage_payload(
        ProviderUsage(input_tokens=100_000, output_tokens=100_000),
        provider_id=provider_id,
        model="gpt-5.4",
    )

    assert "cost_usd" not in payload


def test_public_catalog_models_define_token_pricing_in_the_catalog() -> None:
    assert all(
        item.token_pricing is not None
        for item in initial_model_catalog()
        if item.provider_id != "pgpt"
    )
    assert {
        item.model_key
        for item in initial_model_catalog("pgpt")
        if item.token_pricing is not None
    } == {"gpt-5.6-terra", "gpt-5.6-luna"}


def _settings(tmp_path: Path, name: str, **overrides: Any) -> Settings:
    data_dir = tmp_path / name.removesuffix(".db")
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
        data_dir=data_dir,
        files_dir=data_dir / "files",
        artifacts_dir=data_dir / "artifacts",
        cookie_secure=False,
        **overrides,
    )


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "admin",
            "loginDomain": "posco.com",
            "password": "1111",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrfToken"])


def _start_run(client: TestClient, csrf: str, text: str, key: str) -> str:
    project_id = client.get("/api/projects").json()[0]["id"]
    conversation = client.post(
        "/api/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"projectId": project_id, "title": "Run 제한 검증"},
    )
    assert conversation.status_code == 201, conversation.text
    response = client.post(
        f"/api/conversations/{conversation.json()['id']}/runs",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": key},
        json={
            "message": {
                "text": text,
                "attachmentIds": [],
                "promptReferences": [],
            }
        },
    )
    assert response.status_code == 202, response.text
    return str(response.json()["run"]["runId"])


def _wait_for_terminal(client: TestClient, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}/snapshot")
        assert response.status_code == 200, response.text
        snapshot = response.json()
        if snapshot["status"] in TERMINAL_STATUSES:
            return snapshot
        time.sleep(0.02)
    raise AssertionError(f"Run {run_id} did not become terminal")


def _assert_limit_event(run_id: str, code: str) -> Run:
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        assert run.status == "limit_reached"
        assert run.error_code == code
        events = list(
            db.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id)
                .order_by(RunEvent.sequence)
            )
        )
        limit_event = next(
            event for event in events if event.event_type == "run_limit_reached"
        )
        assert limit_event.payload_json["code"] == code
        assert any(
            event.event_type == "run_failed"
            and event.payload_json["status"] == "limit_reached"
            for event in events
        )
        db.expunge(run)
        return run


def test_run_snapshot_uses_organization_safety_limits(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, "turn-limit.db")
    with TestClient(create_app(settings)) as client:
        run_id = _start_run(
            client,
            _login(client),
            "점검 결과를 HTML 보고서 Artifact로 만들어 주세요.",
            "turn-limit-0001",
        )
        snapshot = _wait_for_terminal(client, run_id)

    assert snapshot["limits"] == {
        "maxModelTurns": 400,
        "maxTotalTokens": 4_000_000,
        "maxElapsedSeconds": 604_800,
        "maxCostUsd": 100.0,
        "costAccounting": "provider_reported_or_estimated",
    }
    assert snapshot["usage"]["model_turns"] >= 1
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        assert run.status == "completed"
        assert run.max_turns == 0


@pytest.mark.parametrize(
    ("name", "settings_overrides", "provider_factory", "expected_code"),
    [
        (
            "token-limit.db",
            {"run_token_limit": 1},
            None,
            "run_token_limit",
        ),
        (
            "cost-limit.db",
            {"run_cost_limit_usd": 0.1},
            lambda: MockProvider(
                usage=ProviderUsage(
                    input_tokens=1,
                    output_tokens=1,
                    raw={"cost_usd": 0.25},
                )
            ),
            "run_cost_limit",
        ),
    ],
)
def test_legacy_usage_limit_settings_do_not_stop_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    settings_overrides: dict[str, Any],
    provider_factory: Callable[[], MockProvider] | None,
    expected_code: str,
) -> None:
    if provider_factory is not None:
        monkeypatch.setattr(
            local_run_executor,
            "_provider",
            lambda _provider_id, *, wants_artifact, first_turn: provider_factory(),
        )
    settings = _settings(tmp_path, name, **settings_overrides)
    with TestClient(create_app(settings)) as client:
        run_id = _start_run(
            client,
            _login(client),
            "제한 경계 테스트입니다.",
            f"{name}-0001",
        )
        _wait_for_terminal(client, run_id)
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        assert run.status == "completed"
        assert not any(
            event.event_type == "run_limit_reached"
            for event in db.scalars(select(RunEvent).where(RunEvent.run_id == run_id))
        )
    if expected_code == "run_cost_limit":
        assert run.usage_json["cost_usd"] == pytest.approx(0.25)


class _SlowProvider:
    provider_id = "mock"
    capabilities = ProviderCapabilities(tools=True)

    async def stream(self, _request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        await asyncio.sleep(0.2)
        yield ProviderEvent(type="text_delta", text="too late")


def test_legacy_deadline_setting_does_not_interrupt_provider_stream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        local_run_executor,
        "_provider",
        lambda _provider_id, *, wants_artifact, first_turn: _SlowProvider(),
    )
    settings = _settings(tmp_path, "deadline.db", run_timeout_seconds=0.05)
    with TestClient(create_app(settings)) as client:
        run_id = _start_run(
            client,
            _login(client),
            "응답 제한 시간을 검증합니다.",
            "deadline-0001",
        )
        _wait_for_terminal(client, run_id)
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None
        assert run.status == "completed"
