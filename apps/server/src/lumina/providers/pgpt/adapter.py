from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace

import httpx

from lumina.http_client import TrustProfile

from ..openai_compatible import OpenAICompatibleAdapter
from ..types import ProviderCapabilities, ProviderEvent, ProviderRequest
from .auth import PgptCredentials, build_pgpt_authorization_header
from .profile import PgptProfile


class PgptAdapter:
    provider_id = "pgpt"
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
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            client=self._client,
            trust_profile=self._trust_profile,
        )
        resolved_request = replace(
            request,
            model=self.profile.resolve_runtime_model(request.model),
        )
        async for event in transport.stream(resolved_request):
            yield event
