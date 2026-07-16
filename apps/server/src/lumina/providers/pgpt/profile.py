from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ..constants import DEFAULT_PGPT_BASE_URL
from ..errors import ProviderConfigurationError
from ..http import validate_http_base_url


@dataclass(frozen=True, slots=True)
class PgptProfile:
    base_url: str = DEFAULT_PGPT_BASE_URL
    api_mode: str = "chat_completions"
    deployment_mapping: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        base_url = validate_http_base_url(self.base_url, "PGPT_BASE_URL")
        if self.api_mode != "chat_completions":
            raise ProviderConfigurationError(
                f"Unsupported P-GPT API mode: {self.api_mode}"
            )
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(
            self,
            "deployment_mapping",
            MappingProxyType(dict(self.deployment_mapping)),
        )

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        deployment_mapping: Mapping[str, str] | None = None,
    ) -> "PgptProfile":
        values = os.environ if env is None else env
        return cls(
            base_url=values.get("PGPT_BASE_URL", "").strip() or DEFAULT_PGPT_BASE_URL,
            deployment_mapping=deployment_mapping or {},
        )

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def resolve_runtime_model(self, model_key: str) -> str:
        return self.deployment_mapping.get(model_key, model_key)
