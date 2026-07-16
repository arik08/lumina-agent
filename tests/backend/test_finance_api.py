from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lumina.api.dependencies import get_current_user
from lumina.api.routes import finance


def _client() -> TestClient:
    application = FastAPI()
    application.include_router(finance.router, prefix="/api")
    application.dependency_overrides[get_current_user] = lambda: object()
    return TestClient(application)


def test_usd_krw_rate_returns_fetched_rate(monkeypatch) -> None:
    async def fake_fetch():
        return {
            "base": "USD",
            "quote": "KRW",
            "rate": 1380.5,
            "asOf": "2026-07-10",
            "source": "Frankfurter",
            "status": "fresh",
        }

    finance._cache = None
    monkeypatch.setattr(finance, "_fetch_usd_krw_rate", fake_fetch)

    response = _client().get("/api/finance/exchange-rate/usd-krw")

    assert response.status_code == 200
    assert response.json()["rate"] == 1380.5
    assert response.json()["status"] == "fresh"


def test_usd_krw_rate_returns_null_when_source_is_unavailable(monkeypatch) -> None:
    fetch_count = 0

    async def failing_fetch():
        nonlocal fetch_count
        fetch_count += 1
        raise RuntimeError("offline")

    finance._cache = None
    monkeypatch.setattr(finance, "_fetch_usd_krw_rate", failing_fetch)

    client = _client()
    response = client.get("/api/finance/exchange-rate/usd-krw")
    cached_response = client.get("/api/finance/exchange-rate/usd-krw")

    assert response.status_code == 200
    assert response.json()["rate"] is None
    assert response.json()["status"] == "unavailable"
    assert cached_response.json() == response.json()
    assert fetch_count == 1


def test_usd_krw_rate_keeps_last_rate_when_refresh_fails(monkeypatch) -> None:
    fetch_count = 0

    async def failing_fetch():
        nonlocal fetch_count
        fetch_count += 1
        raise RuntimeError("offline")

    finance._cache = {
        "base": "USD",
        "quote": "KRW",
        "rate": 1380.5,
        "asOf": "2026-07-10",
        "source": "Frankfurter",
        "status": "fresh",
    }
    finance._cache_expires_at = datetime.min.replace(tzinfo=UTC)
    monkeypatch.setattr(finance, "_fetch_usd_krw_rate", failing_fetch)

    client = _client()
    response = client.get("/api/finance/exchange-rate/usd-krw")
    cached_response = client.get("/api/finance/exchange-rate/usd-krw")

    assert response.status_code == 200
    assert response.json() == {
        "base": "USD",
        "quote": "KRW",
        "rate": 1380.5,
        "asOf": "2026-07-10",
        "source": "Frankfurter",
        "status": "stale",
    }
    assert cached_response.json() == response.json()
    assert fetch_count == 1
