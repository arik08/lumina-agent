from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace

import httpx

from typing import Any

from lumina.http_client import (
    HttpClientOptions,
    TrustManager,
    TrustProfile,
    create_http_client,
)

from ..constants import PGPT_PROVIDER_ID
from ..errors import ProviderRequestError
from ..openai import OpenAIResponsesAdapter
from ..openai_compatible import OpenAICompatibleAdapter, build_chat_completions_payload
from ..types import ProviderCapabilities, ProviderEvent, ProviderRequest
from .auth import PgptCredentials, build_pgpt_authorization_header
from .profile import PgptProfile


DEFAULT_PGPT_MAX_COMPLETION_TOKENS = 42_000
PROVIDER_ID = PGPT_PROVIDER_ID
_UNSUPPORTED_PGPT_JSON_SCHEMA_KEYWORDS = frozenset(
    {"allOf", "oneOf", "if", "then", "const"}
)


def _simplify_pgpt_json_schema(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _simplify_pgpt_json_schema(item)
            for key, item in value.items()
            if key not in _UNSUPPORTED_PGPT_JSON_SCHEMA_KEYWORDS
        }
    if isinstance(value, (list, tuple)):
        return [_simplify_pgpt_json_schema(item) for item in value]
    return value


def _simplify_pgpt_tool_schemas(payload: dict[str, Any]) -> None:
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return
    simplified_tools: list[Any] = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            simplified_tools.append(tool)
            continue
        simplified_tool = dict(tool)
        function = tool.get("function")
        if isinstance(function, Mapping):
            simplified_function = dict(function)
            parameters = function.get("parameters")
            if isinstance(parameters, Mapping):
                simplified_function["parameters"] = _simplify_pgpt_json_schema(parameters)
            simplified_tool["function"] = simplified_function
        parameters = tool.get("parameters")
        if isinstance(parameters, Mapping):
            simplified_tool["parameters"] = _simplify_pgpt_json_schema(parameters)
        simplified_tools.append(simplified_tool)
    payload["tools"] = simplified_tools


def build_pgpt_payload(request: ProviderRequest) -> dict[str, Any]:
    """Build the streaming subset accepted by the company P-GPT gateway."""
    payload = build_chat_completions_payload(request)
    _simplify_pgpt_tool_schemas(payload)
    payload.setdefault(
        "max_completion_tokens",
        DEFAULT_PGPT_MAX_COMPLETION_TOKENS,
    )
    payload.pop("response_format", None)
    cache_key = request.metadata.get("prompt_cache_key")
    if isinstance(cache_key, str) and cache_key:
        payload["prompt_cache_key"] = cache_key
        retention = request.metadata.get("prompt_cache_retention")
        if retention in {"in_memory", "24h"}:
            payload["prompt_cache_retention"] = retention
    return payload


def build_pgpt_responses_payload(
    request: ProviderRequest, payload: dict[str, Any]
) -> dict[str, Any]:
    """Keep P-GPT compatibility conversion at its Responses wire boundary."""

    _simplify_pgpt_tool_schemas(payload)
    payload.setdefault("max_output_tokens", DEFAULT_PGPT_MAX_COMPLETION_TOKENS)
    return payload


class PgptAdapter:
    provider_id = PROVIDER_ID
    capabilities = ProviderCapabilities(
        tools=True,
        structured_output=True,
        reasoning_effort=True,
    )

    def __init__(
        self,
        *,
        profile: PgptProfile | None = None,
        credentials: PgptCredentials | None = None,
        env: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        trust_profile: TrustProfile | None = None,
    ) -> None:
        self._env = dict(os.environ if env is None else env)
        self.profile = profile or PgptProfile.from_env(self._env)
        self._credentials = credentials
        self._client = client
        self._trust_profile = trust_profile
        self._transport: OpenAICompatibleAdapter | None = None
        self._responses_transport: OpenAIResponsesAdapter | None = None
        self._responses_endpoint_unavailable = False
        self._transport_lock = asyncio.Lock()
        self._owns_client = False

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        resolved_request = replace(
            request,
            model=self.profile.resolve_runtime_model(request.model),
        )
        if self.supports_server_compaction(resolved_request.model):
            responses_transport = await self._get_responses_transport()
            emitted = False
            try:
                async for event in responses_transport.stream(resolved_request):
                    emitted = True
                    yield event
                return
            except ProviderRequestError as exc:
                if emitted or exc.status_code not in {404, 405}:
                    raise
                self._responses_endpoint_unavailable = True
        transport = await self._get_transport()
        async for event in transport.stream(resolved_request):
            yield event

    def supports_server_compaction(self, model: str) -> bool:
        return (
            model.casefold().startswith("gpt-5.6")
            and not self._responses_endpoint_unavailable
        )

    async def close(self) -> None:
        async with self._transport_lock:
            client = self._client
            owns_client = self._owns_client
            self._transport = None
            self._responses_transport = None
            self._client = None
            self._owns_client = False
        if owns_client and client is not None:
            await client.aclose()

    async def _get_transport(self) -> OpenAICompatibleAdapter:
        if self._transport is not None:
            return self._transport
        async with self._transport_lock:
            if self._transport is not None:
                return self._transport
            credentials = self._credentials or PgptCredentials.from_env(self._env)
            authorization = build_pgpt_authorization_header(credentials)
            client = self._client
            if client is None:
                profile = self._trust_profile or TrustManager().initialize()
                client = create_http_client(
                    profile,
                    options=HttpClientOptions(
                        timeout_seconds=self.profile.timeout_seconds,
                        follow_redirects=True,
                    ),
                )
                self._client = client
                self._owns_client = True
            self._transport = OpenAICompatibleAdapter(
                provider_id=self.provider_id,
                base_url=self.profile.base_url,
                headers={
                    "Authorization": authorization,
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                },
                client=client,
                payload_builder=build_pgpt_payload,
                optional_payload_fields=(
                    "reasoning_effort",
                    "stream_options",
                    "prompt_cache_key",
                    "prompt_cache_retention",
                ),
            )
            return self._transport

    async def _get_responses_transport(self) -> OpenAIResponsesAdapter:
        if self._responses_transport is not None:
            return self._responses_transport
        async with self._transport_lock:
            if self._responses_transport is not None:
                return self._responses_transport
            credentials = self._credentials or PgptCredentials.from_env(self._env)
            authorization = build_pgpt_authorization_header(credentials)
            client = self._client
            if client is None:
                profile = self._trust_profile or TrustManager().initialize()
                client = create_http_client(
                    profile,
                    options=HttpClientOptions(
                        timeout_seconds=self.profile.timeout_seconds,
                        follow_redirects=True,
                    ),
                )
                self._client = client
                self._owns_client = True
            self._responses_transport = OpenAIResponsesAdapter(
                api_key="pgpt-authorization-is-provided-by-additional-headers",
                base_url=self.profile.base_url,
                client=client,
                additional_headers={
                    "Authorization": authorization,
                    "Content-Type": "application/json",
                },
                payload_transform=build_pgpt_responses_payload,
                service_name="P-GPT Responses",
            )
            return self._responses_transport
