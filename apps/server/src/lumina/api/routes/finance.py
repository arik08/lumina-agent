from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal, TypedDict

from fastapi import APIRouter, Depends

from ...config import REPOSITORY_ROOT
from ...http_client import HttpClientOptions, TrustManager, create_http_client
from ...models import User
from ..dependencies import get_current_user


router = APIRouter(prefix="/finance", tags=["finance"])

_RATE_URL = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=KRW"
_CACHE_TTL = timedelta(hours=6)
_FAILURE_CACHE_TTL = timedelta(minutes=5)


class ExchangeRatePayload(TypedDict):
    base: Literal["USD"]
    quote: Literal["KRW"]
    rate: float | None
    asOf: str | None
    source: str | None
    status: Literal["fresh", "stale", "unavailable"]


_cache: ExchangeRatePayload | None = None
_cache_expires_at = datetime.min.replace(tzinfo=UTC)
_cache_lock = asyncio.Lock()


async def _fetch_usd_krw_rate() -> ExchangeRatePayload:
    profile = TrustManager(repo_root=REPOSITORY_ROOT).initialize()
    async with create_http_client(
        profile,
        options=HttpClientOptions(timeout_seconds=5.0),
        headers={"Accept": "application/json"},
    ) as client:
        response = await client.get(_RATE_URL)
        response.raise_for_status()
        payload = response.json()

    rate = float(payload["rates"]["KRW"])
    if rate <= 0:
        raise ValueError("USD/KRW rate must be positive")
    return {
        "base": "USD",
        "quote": "KRW",
        "rate": rate,
        "asOf": str(payload["date"]),
        "source": "Frankfurter",
        "status": "fresh",
    }


def _unavailable_rate() -> ExchangeRatePayload:
    return {
        "base": "USD",
        "quote": "KRW",
        "rate": None,
        "asOf": None,
        "source": None,
        "status": "unavailable",
    }


@router.get("/exchange-rate/usd-krw")
async def get_usd_krw_rate(
    _user: User = Depends(get_current_user),
) -> ExchangeRatePayload:
    global _cache, _cache_expires_at

    now = datetime.now(UTC)
    if _cache is not None and now < _cache_expires_at:
        return _cache

    async with _cache_lock:
        now = datetime.now(UTC)
        if _cache is not None and now < _cache_expires_at:
            return _cache
        try:
            _cache = await _fetch_usd_krw_rate()
            _cache_expires_at = now + _CACHE_TTL
            return _cache
        except Exception:
            if _cache is not None and _cache["rate"] is not None:
                _cache = {**_cache, "status": "stale"}
            else:
                _cache = _unavailable_rate()
            _cache_expires_at = now + _FAILURE_CACHE_TTL
            return _cache
