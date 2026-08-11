from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import platform
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import httpx

from ..catalog import initial_model_catalog
from ..constants import CODEX_PROVIDER_ID
from ..errors import ProviderConfigurationError, ProviderRequestError
from ..openai import OpenAIResponsesAdapter
from ..types import ProviderCapabilities, ProviderEvent, ProviderRequest, ProviderUsage


PROVIDER_ID = CODEX_PROVIDER_ID
_CODEX_RESPONSES_BASE_URL = "https://chatgpt.com/backend-api/codex"
_CODEX_JWT_AUTH_CLAIM = "https://api.openai.com/auth"
_CODEX_OAUTH_MODELS = frozenset(
    item.runtime_model_id for item in initial_model_catalog(PROVIDER_ID)
)


def _oauth_model_available(model: str) -> bool:
    return model in _CODEX_OAUTH_MODELS


def codex_oauth_available() -> bool:
    """Return whether a readable local ChatGPT OAuth token is available."""

    try:
        _codex_account_id(_codex_access_token())
    except ProviderConfigurationError:
        return False
    return True


class CodexResponsesAdapter:
    """ChatGPT OAuth adapter using Lumina's direct Responses transport."""

    provider_id = PROVIDER_ID
    capabilities = ProviderCapabilities(
        tools=True,
        structured_output=True,
        reasoning_effort=True,
    )

    def __init__(self) -> None:
        self._client_lock = asyncio.Lock()
        self._responses_client: httpx.AsyncClient | None = None

    async def close(self) -> None:
        async with self._client_lock:
            client = self._responses_client
            self._responses_client = None
            if client is not None:
                await client.aclose()

    async def warmup(self) -> None:
        """Validate the local Codex OAuth file without starting a subprocess."""

        _codex_account_id(_codex_access_token())

    async def prewarm(self, request: ProviderRequest) -> ProviderUsage | None:
        """Populate the Direct Responses prefix cache without exposing output."""

        usage: ProviderUsage | None = None
        async for event in self._stream_direct(request):
            if event.type == "usage" and event.usage is not None:
                usage = event.usage
        return usage

    async def _ready_responses_client(self) -> httpx.AsyncClient:
        async with self._client_lock:
            if self._responses_client is None:
                self._responses_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(180.0, connect=30.0, write=60.0),
                    follow_redirects=True,
                )
            return self._responses_client

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        async for event in self._stream_direct(request):
            yield event

    async def _stream_direct(
        self, request: ProviderRequest
    ) -> AsyncIterator[ProviderEvent]:
        if not _oauth_model_available(request.model):
            raise ProviderConfigurationError(
                f"Codex OAuth에서 사용할 수 없는 모델입니다: {request.model}"
            )

        token = _codex_access_token()
        headers = _codex_responses_headers(token, request)
        responses_client = await self._ready_responses_client()
        delegate = OpenAIResponsesAdapter(
            api_key=token,
            base_url=_CODEX_RESPONSES_BASE_URL,
            client=responses_client,
            additional_headers=headers,
            payload_transform=_codex_responses_payload,
            service_name="Codex Responses",
        )
        try:
            async for event in delegate.stream(request):
                if event.type == "usage" and event.usage is not None:
                    usage = event.usage
                    event = ProviderEvent(
                        type="usage",
                        usage=ProviderUsage(
                            input_tokens=usage.input_tokens,
                            cached_input_tokens=usage.cached_input_tokens,
                            cache_write_tokens=usage.cache_write_tokens,
                            uncached_input_tokens=usage.uncached_input_tokens,
                            output_tokens=usage.output_tokens,
                            reasoning_tokens=usage.reasoning_tokens,
                            raw={
                                **dict(usage.raw),
                                "auth_mode": "chatgpt",
                                "billing": "subscription_usage",
                            },
                        ),
                    )
                yield event
        except ProviderRequestError as exc:
            if exc.status_code == 401:
                raise ProviderRequestError(
                    "Codex ChatGPT OAuth 인증이 만료되었습니다. `codex login`을 다시 실행해 주세요.",
                    retryable=False,
                    stage="authentication",
                    status_code=401,
                ) from exc
            raise


def _codex_auth_path() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "auth.json"


def _codex_access_token() -> str:
    path = _codex_auth_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderConfigurationError(
            "Codex ChatGPT OAuth 인증 파일을 읽을 수 없습니다. "
            "서버 사용자 계정에서 `codex login`을 실행해 주세요."
        ) from exc
    tokens = payload.get("tokens")
    token = tokens.get("access_token") if isinstance(tokens, Mapping) else None
    if not isinstance(token, str) or not token:
        fallback = payload.get("OPENAI_API_KEY")
        token = fallback if isinstance(fallback, str) else None
    if not token:
        raise ProviderConfigurationError(
            "Codex ChatGPT OAuth access token을 찾을 수 없습니다."
        )
    return token


def _codex_account_id(token: str) -> str:
    parts = token.split(".")
    if len(parts) != 3:
        raise ProviderConfigurationError(
            "Codex OAuth access token 형식이 올바르지 않습니다."
        )
    try:
        encoded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderConfigurationError(
            "Codex OAuth access token의 계정 정보를 읽을 수 없습니다."
        ) from exc
    auth = payload.get(_CODEX_JWT_AUTH_CLAIM)
    account_id = auth.get("chatgpt_account_id") if isinstance(auth, Mapping) else None
    if not isinstance(account_id, str) or not account_id:
        raise ProviderConfigurationError(
            "Codex OAuth access token에 ChatGPT 계정 정보가 없습니다."
        )
    return account_id


def _codex_cache_session_id(request: ProviderRequest) -> str | None:
    cache_key = request.metadata.get("prompt_cache_key")
    if not isinstance(cache_key, str) or not cache_key:
        return None
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:24]
    return f"lumina-cache-{digest}"


def _codex_responses_headers(token: str, request: ProviderRequest) -> dict[str, str]:
    headers = {
        "chatgpt-account-id": _codex_account_id(token),
        "originator": "lumina_agent",
        "User-Agent": (
            f"lumina-agent ({platform.system().lower()} "
            f"{platform.machine() or 'unknown'})"
        ),
        "OpenAI-Beta": "responses=experimental",
        "Content-Type": "application/json",
    }
    session_id = _codex_cache_session_id(request)
    if session_id is not None:
        headers["session-id"] = session_id
    return headers


def _codex_responses_payload(
    request: ProviderRequest, payload: dict[str, Any]
) -> dict[str, Any]:
    _strip_prompt_cache_breakpoints(payload)
    transformed_input: list[dict[str, Any]] = []
    for item in payload.get("input", []):
        if not isinstance(item, Mapping):
            continue
        converted = dict(item)
        role = converted.get("role")
        content = converted.get("content")
        if role in {"system", "user"}:
            converted["role"] = "developer" if role == "system" else "user"
            if isinstance(content, str):
                converted["content"] = [{"type": "input_text", "text": content}]
        elif role == "assistant" and isinstance(content, str):
            converted = {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": content,
                        "annotations": [],
                    }
                ],
            }
        elif converted.get("type") == "function_call":
            call_id = str(converted.get("call_id") or "")
            converted.setdefault(
                "id", f"fc_{hashlib.sha256(call_id.encode()).hexdigest()[:24]}"
            )
        transformed_input.append(converted)
    payload["input"] = transformed_input
    payload["instructions"] = (
        "You are the language-model boundary inside Lumina Agent. "
        "Use only the function tools supplied in this request."
    )
    payload["include"] = ["reasoning.encrypted_content"]
    if request.tools:
        payload["tool_choice"] = "auto"
        payload["parallel_tool_calls"] = True
    payload.pop("prompt_cache_options", None)
    payload.pop("prompt_cache_retention", None)
    payload.pop("max_output_tokens", None)
    payload.pop("temperature", None)
    return payload


def _strip_prompt_cache_breakpoints(value: Any) -> None:
    if isinstance(value, dict):
        value.pop("prompt_cache_breakpoint", None)
        for nested in value.values():
            _strip_prompt_cache_breakpoints(nested)
    elif isinstance(value, list):
        for nested in value:
            _strip_prompt_cache_breakpoints(nested)


__all__ = ["CodexResponsesAdapter", "codex_oauth_available"]
