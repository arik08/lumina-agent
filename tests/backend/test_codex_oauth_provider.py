from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx
import pytest

from lumina.providers import (
    ProviderConfigurationError,
    ProviderEvent,
    ProviderMessage,
    ProviderRequest,
    ProviderRequestError,
    ProviderUsage,
)
from lumina.providers.codex import CodexResponsesAdapter, codex_oauth_available
from lumina.providers.codex import adapter as codex_adapter


def _test_codex_token(
    account_id: str = "acct-test", *, expires_at: float | None = None
) -> str:
    header = base64.urlsafe_b64encode(b"{}").decode().rstrip("=")
    payload: dict[str, Any] = {
        "https://api.openai.com/auth": {"chatgpt_account_id": account_id}
    }
    if expires_at is not None:
        payload["exp"] = expires_at
    claims = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).decode().rstrip("=")
    return f"{header}.{claims}.signature"


def _write_codex_auth(
    codex_home,
    *,
    token: str | None = None,
    refresh_token: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    codex_home.mkdir(exist_ok=True)
    tokens = {"access_token": token or _test_codex_token()}
    if refresh_token is not None:
        tokens["refresh_token"] = refresh_token
    payload = {"tokens": tokens, **(extra or {})}
    (codex_home / "auth.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize(
    "model",
    ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"],
)
def test_codex_oauth_allows_reviewed_catalog_models(model: str) -> None:
    assert codex_adapter._oauth_model_available(model)


def test_codex_oauth_rejects_unreviewed_model() -> None:
    assert not codex_adapter._oauth_model_available("gpt-future-unreviewed")


def test_codex_oauth_availability_reads_auth_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex-home"
    _write_codex_auth(codex_home)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    assert codex_oauth_available() is True


def test_codex_oauth_availability_rejects_missing_or_invalid_auth(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    assert codex_oauth_available() is False

    _write_codex_auth(codex_home, token="not-a-jwt")
    assert codex_oauth_available() is False

    _write_codex_auth(
        codex_home,
        extra={"auth_mode": "apikey"},
    )
    assert codex_oauth_available() is False


def test_codex_oauth_availability_requires_usable_or_refreshable_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex-home"
    expired = _test_codex_token(expires_at=time.time() - 60)
    _write_codex_auth(codex_home, token=expired)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    assert codex_oauth_available() is False

    _write_codex_auth(codex_home, token=expired, refresh_token="refresh-old")
    assert codex_oauth_available() is True


@pytest.mark.asyncio
async def test_codex_warmup_validates_auth_without_starting_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex-home"
    _write_codex_auth(codex_home)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    adapter = CodexResponsesAdapter()
    await adapter.warmup()
    await adapter.close()


@pytest.mark.asyncio
async def test_codex_warmup_reports_missing_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing"))

    with pytest.raises(ProviderConfigurationError, match="codex login"):
        await CodexResponsesAdapter().warmup()


@pytest.mark.asyncio
async def test_codex_proactively_refreshes_expiring_token_and_preserves_auth_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex-home"
    expired = _test_codex_token(expires_at=time.time() - 60)
    fresh = _test_codex_token(expires_at=time.time() + 3600)
    _write_codex_auth(
        codex_home,
        token=expired,
        refresh_token="refresh-old",
        extra={"auth_mode": "chatgpt", "custom": {"preserve": True}},
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_REFRESH_TOKEN_URL_OVERRIDE", "https://auth.test/oauth/token")
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.host == "auth.test":
            assert json.loads(request.content) == {
                "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
                "grant_type": "refresh_token",
                "refresh_token": "refresh-old",
            }
            return httpx.Response(
                200,
                json={
                    "access_token": fresh,
                    "refresh_token": "refresh-new",
                },
            )
        assert request.headers["authorization"] == f"Bearer {fresh}"
        response = {
            "type": "response.completed",
            "response": {"output": [], "usage": {}},
        }
        return httpx.Response(200, content=f"data: {json.dumps(response)}\n\n".encode())

    adapter = CodexResponsesAdapter()
    adapter._responses_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    _events = [
        event
        async for event in adapter.stream(
            ProviderRequest(
                model="gpt-5.6-luna",
                messages=(ProviderMessage(role="user", content="hello"),),
            )
        )
    ]

    saved = json.loads((codex_home / "auth.json").read_text(encoding="utf-8"))
    assert calls == ["/oauth/token", "/backend-api/codex/responses"]
    assert saved["tokens"]["access_token"] == fresh
    assert saved["tokens"]["refresh_token"] == "refresh-new"
    assert saved["custom"] == {"preserve": True}
    assert saved["last_refresh"].endswith("Z")
    await adapter.close()


@pytest.mark.asyncio
async def test_codex_direct_routes_same_prefix_across_new_run_sessions(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex-home"
    _write_codex_auth(codex_home)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    captured: list[tuple[httpx.Headers, dict[str, Any]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.append((request.headers, payload))
        response = {
            "type": "response.completed",
            "response": {
                "output": [],
                "usage": {
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 85},
                    "output_tokens": 4,
                },
            },
        }
        return httpx.Response(200, content=f"data: {json.dumps(response)}\n\n".encode())

    adapter = CodexResponsesAdapter()
    adapter._responses_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    cache_key = "lumina:user:v2:shared-static-prefix"
    for run_id, task in (("session-a", "first task"), ("session-b", "next task")):
        events = [
            event
            async for event in adapter.stream(
                ProviderRequest(
                    model="gpt-5.6-luna",
                    messages=(
                        ProviderMessage(role="system", content="stable system"),
                        ProviderMessage(role="user", content=task),
                    ),
                    metadata={
                        "prompt_cache_key": cache_key,
                        "prompt_cache_retention": "24h",
                        "codex_run_thread_id": run_id,
                    },
                    max_output_tokens=32,
                    temperature=0.2,
                )
            )
        ]
        assert events[-2].usage is not None
        assert events[-2].usage.cached_input_tokens == 85
        assert events[-2].usage.raw["billing"] == "subscription_usage"

    assert len(captured) == 2
    assert captured[0][0]["session-id"] == captured[1][0]["session-id"]
    assert "session_id" not in captured[0][0]
    assert captured[0][0]["chatgpt-account-id"] == "acct-test"
    assert captured[0][1]["prompt_cache_key"] == cache_key
    assert captured[1][1]["prompt_cache_key"] == cache_key
    assert "max_output_tokens" not in captured[0][1]
    assert "temperature" not in captured[0][1]
    assert "prompt_cache_retention" not in captured[0][1]
    assert "prompt_cache_options" not in captured[0][1]
    assert captured[0][1]["input"][0] == {
        "role": "developer",
        "content": [{"type": "input_text", "text": "stable system"}],
    }
    await adapter.close()


@pytest.mark.asyncio
async def test_codex_oauth_prewarm_returns_direct_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = CodexResponsesAdapter()
    request = ProviderRequest(
        model="gpt-5.5",
        messages=(ProviderMessage(role="user", content="prime"),),
    )

    async def direct_stream(actual_request: ProviderRequest):
        assert actual_request is request
        yield ProviderEvent(
            type="usage",
            usage=ProviderUsage(
                input_tokens=100,
                cached_input_tokens=85,
                uncached_input_tokens=15,
                output_tokens=1,
            ),
        )
        yield ProviderEvent(type="completed", stop_reason="stop")

    monkeypatch.setattr(adapter, "_stream_direct", direct_stream)

    usage = await adapter.prewarm(request)

    assert usage is not None
    assert usage.cached_input_tokens == 85


@pytest.mark.asyncio
async def test_codex_direct_rejects_unknown_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex-home"
    _write_codex_auth(codex_home)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    with pytest.raises(ProviderConfigurationError, match="사용할 수 없는 모델"):
        _events = [
            event
            async for event in CodexResponsesAdapter().stream(
                ProviderRequest(
                    model="gpt-future-unreviewed",
                    messages=(ProviderMessage(role="user", content="hello"),),
                )
            )
        ]


@pytest.mark.asyncio
async def test_codex_direct_401_requests_fresh_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex-home"
    _write_codex_auth(codex_home)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "expired"})

    adapter = CodexResponsesAdapter()
    adapter._responses_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ProviderRequestError, match="codex login") as captured:
        _events = [
            event
            async for event in adapter.stream(
                ProviderRequest(
                    model="gpt-5.6-luna",
                    messages=(ProviderMessage(role="user", content="hello"),),
                )
            )
        ]

    assert captured.value.retryable is False
    assert captured.value.stage == "authentication"
    assert captured.value.status_code == 401
    await adapter.close()


@pytest.mark.asyncio
async def test_codex_direct_401_reloads_token_refreshed_by_another_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex-home"
    stale = _test_codex_token(expires_at=time.time() + 3600)
    fresh = _test_codex_token(expires_at=time.time() + 7200)
    _write_codex_auth(codex_home, token=stale, refresh_token="refresh-old")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    seen_tokens: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_tokens.append(request.headers["authorization"])
        if len(seen_tokens) == 1:
            _write_codex_auth(
                codex_home,
                token=fresh,
                refresh_token="refresh-new",
            )
            return httpx.Response(401, json={"error": "stale"})
        response = {
            "type": "response.completed",
            "response": {"output": [], "usage": {}},
        }
        return httpx.Response(200, content=f"data: {json.dumps(response)}\n\n".encode())

    adapter = CodexResponsesAdapter()
    adapter._responses_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    events = [
        event
        async for event in adapter.stream(
            ProviderRequest(
                model="gpt-5.6-luna",
                messages=(ProviderMessage(role="user", content="hello"),),
            )
        )
    ]

    assert seen_tokens == [f"Bearer {stale}", f"Bearer {fresh}"]
    assert events[-1].type == "completed"
    await adapter.close()


@pytest.mark.asyncio
async def test_codex_direct_401_refreshes_and_retries_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex-home"
    stale = _test_codex_token(expires_at=time.time() + 3600)
    fresh = _test_codex_token(expires_at=time.time() + 7200)
    _write_codex_auth(codex_home, token=stale, refresh_token="refresh-old")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_REFRESH_TOKEN_URL_OVERRIDE", "https://auth.test/oauth/token")
    calls: list[tuple[str, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        authorization = request.headers.get("authorization")
        calls.append((request.url.host or "", authorization))
        if request.url.host == "auth.test":
            return httpx.Response(200, json={"access_token": fresh})
        if authorization == f"Bearer {stale}":
            return httpx.Response(401, json={"error": "expired"})
        response = {
            "type": "response.completed",
            "response": {"output": [], "usage": {}},
        }
        return httpx.Response(200, content=f"data: {json.dumps(response)}\n\n".encode())

    adapter = CodexResponsesAdapter()
    adapter._responses_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    events = [
        event
        async for event in adapter.stream(
            ProviderRequest(
                model="gpt-5.6-luna",
                messages=(ProviderMessage(role="user", content="hello"),),
            )
        )
    ]

    assert calls == [
        ("chatgpt.com", f"Bearer {stale}"),
        ("auth.test", None),
        ("chatgpt.com", f"Bearer {fresh}"),
    ]
    assert events[-1].type == "completed"
    await adapter.close()


@pytest.mark.asyncio
async def test_codex_direct_retries_stream_failure_only_before_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex-home"
    _write_codex_auth(codex_home)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    attempts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            failed = {"type": "response.failed", "response": {"status": "failed"}}
            return httpx.Response(
                200, content=f"data: {json.dumps(failed)}\n\n".encode()
            )
        completed = {
            "type": "response.completed",
            "response": {"output": [], "usage": {}},
        }
        return httpx.Response(
            200, content=f"data: {json.dumps(completed)}\n\n".encode()
        )

    adapter = CodexResponsesAdapter()
    adapter._responses_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    events = [
        event
        async for event in adapter.stream(
            ProviderRequest(
                model="gpt-5.6-luna",
                messages=(ProviderMessage(role="user", content="hello"),),
            )
        )
    ]

    assert attempts == 2
    assert events[-1].type == "completed"
    await adapter.close()


@pytest.mark.asyncio
async def test_codex_direct_does_not_retry_after_output_started(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex-home"
    _write_codex_auth(codex_home)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    attempts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        delta = {"type": "response.output_text.delta", "delta": "partial"}
        failed = {"type": "response.failed", "response": {"status": "failed"}}
        body = f"data: {json.dumps(delta)}\n\ndata: {json.dumps(failed)}\n\n"
        return httpx.Response(200, content=body.encode())

    adapter = CodexResponsesAdapter()
    adapter._responses_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderRequestError, match="unknown"):
        _events = [
            event
            async for event in adapter.stream(
                ProviderRequest(
                    model="gpt-5.6-luna",
                    messages=(ProviderMessage(role="user", content="hello"),),
                )
            )
        ]

    assert attempts == 1
    await adapter.close()
