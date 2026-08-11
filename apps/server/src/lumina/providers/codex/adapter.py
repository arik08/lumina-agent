from __future__ import annotations

import asyncio
import hashlib
import platform
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from ..catalog import initial_model_catalog
from ..constants import CODEX_PROVIDER_ID
from ..errors import ProviderConfigurationError, ProviderRequestError
from ..openai import OpenAIResponsesAdapter
from ..types import ProviderCapabilities, ProviderEvent, ProviderRequest, ProviderUsage
from .auth import (
    CodexAuthCredentials,
    codex_oauth_available,
    ready_codex_auth,
    refresh_codex_auth,
)


PROVIDER_ID = CODEX_PROVIDER_ID
_CODEX_RESPONSES_BASE_URL = "https://chatgpt.com/backend-api/codex"
_CODEX_OAUTH_MODELS = frozenset(
    item.runtime_model_id for item in initial_model_catalog(PROVIDER_ID)
)


def _oauth_model_available(model: str) -> bool:
    return model in _CODEX_OAUTH_MODELS


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
        """Validate and, when needed, refresh local Codex OAuth."""

        await ready_codex_auth(await self._ready_responses_client())

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

        responses_client = await self._ready_responses_client()
        credentials = await ready_codex_auth(responses_client)
        for attempt in range(2):
            emitted_event = False
            try:
                async for event in self._stream_with_auth(
                    request, responses_client, credentials
                ):
                    emitted_event = True
                    yield event
                return
            except ProviderRequestError as exc:
                if emitted_event or attempt > 0:
                    raise
                if exc.status_code == 401:
                    credentials = await refresh_codex_auth(
                        responses_client,
                        observed_access_token=credentials.access_token,
                        trigger_status_code=401,
                    )
                    continue
                if exc.stage != "stream" or exc.status_code is not None:
                    raise

        raise AssertionError("Codex OAuth retry loop exhausted")

    async def _stream_with_auth(
        self,
        request: ProviderRequest,
        responses_client: httpx.AsyncClient,
        credentials: CodexAuthCredentials,
    ) -> AsyncIterator[ProviderEvent]:
        delegate = OpenAIResponsesAdapter(
            api_key=credentials.access_token,
            base_url=_CODEX_RESPONSES_BASE_URL,
            client=responses_client,
            additional_headers=_codex_responses_headers(credentials, request),
            payload_transform=_codex_responses_payload,
            service_name="Codex Responses",
        )
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


def _codex_cache_session_id(request: ProviderRequest) -> str | None:
    cache_key = request.metadata.get("prompt_cache_key")
    if not isinstance(cache_key, str) or not cache_key:
        return None
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:24]
    return f"lumina-cache-{digest}"


def _codex_responses_headers(
    credentials: CodexAuthCredentials, request: ProviderRequest
) -> dict[str, str]:
    headers = {
        "chatgpt-account-id": credentials.account_id,
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
