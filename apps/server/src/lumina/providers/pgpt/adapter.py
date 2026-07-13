from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace

import httpx

from typing import Any

from lumina.http_client import HttpClientOptions, TrustProfile

from ..constants import PGPT_PROVIDER_ID
from ..openai_compatible import OpenAICompatibleAdapter, build_chat_completions_payload
from ..types import ProviderCapabilities, ProviderEvent, ProviderRequest
from .auth import PgptCredentials, build_pgpt_authorization_header
from .profile import PgptProfile


DEFAULT_PGPT_MAX_COMPLETION_TOKENS = 42_000
PROVIDER_ID = PGPT_PROVIDER_ID


def build_pgpt_payload(request: ProviderRequest) -> dict[str, Any]:
    """Build the streaming subset accepted by the company P-GPT gateway."""
    payload = build_chat_completions_payload(request)
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

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        credentials = self._credentials or PgptCredentials.from_env(self._env)
        authorization = build_pgpt_authorization_header(credentials)
        transport = OpenAICompatibleAdapter(
            provider_id=self.provider_id,
            base_url=self.profile.base_url,
            headers={
                "Authorization": authorization,
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            },
            client=self._client,
            trust_profile=self._trust_profile,
            http_options=HttpClientOptions(
                timeout_seconds=self.profile.timeout_seconds,
                follow_redirects=True,
            ),
            payload_builder=build_pgpt_payload,
        )
        resolved_request = replace(
            request,
            model=self.profile.resolve_runtime_model(request.model),
        )
        async for event in transport.stream(resolved_request):
            yield event
