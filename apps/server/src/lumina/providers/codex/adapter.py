from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from lumina.http_client import TrustProfile

from ..openai import DEFAULT_OPENAI_BASE_URL, OpenAIResponsesAdapter
from ..types import ProviderCapabilities, ProviderEvent, ProviderRequest


class CodexResponsesAdapter:
    """Codex text adapter using the approved OpenAI Responses credential path."""

    provider_id = "codex"
    capabilities = ProviderCapabilities(
        tools=True,
        structured_output=True,
        reasoning_effort=True,
        image_generation=True,
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_OPENAI_BASE_URL,
        client: httpx.AsyncClient | None = None,
        trust_profile: TrustProfile | None = None,
    ) -> None:
        self._responses = OpenAIResponsesAdapter(
            api_key=api_key,
            base_url=base_url,
            client=client,
            trust_profile=trust_profile,
        )

    @property
    def base_url(self) -> str:
        return self._responses.base_url

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        async for event in self._responses.stream(request):
            yield event


__all__ = ["CodexResponsesAdapter"]
