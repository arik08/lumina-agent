from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from .types import ProviderCapabilities

CATALOG_REVISION = "2026-07-12.2-codex-oauth"
CATALOG_VERIFIED_AT = date(2026, 7, 12)


@dataclass(frozen=True, slots=True)
class ModelCatalogSeed:
    provider_id: str
    model_key: str
    display_name: str
    runtime_model_id: str
    is_default: bool
    sort_order: int
    source: str
    aliases: tuple[str, ...] = ()
    enabled: bool = True
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)
    catalog_revision: str = CATALOG_REVISION
    verified_at: date = CATALOG_VERIFIED_AT

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_PRODUCT_CONTRACT = "product_contract"
_OFFICIAL_2026_07_11 = "official_docs_2026-07-11"
_PGPT_CAPABILITIES = ProviderCapabilities(
    tools=True,
    structured_output=True,
    reasoning_effort=True,
    context_window=1_050_000,
)
_PGPT_MINI_CAPABILITIES = ProviderCapabilities(
    tools=True,
    structured_output=True,
    reasoning_effort=True,
    context_window=400_000,
)
_CODEX_TEXT_CAPABILITIES = ProviderCapabilities(
    tools=True,
    structured_output=True,
    reasoning_effort=True,
    context_window=272_000,
)
_GOOGLE_CAPABILITIES = ProviderCapabilities(
    tools=True,
    structured_output=True,
    context_window=1_000_000,
    max_output_tokens=64_000,
)
_OPENAI_CAPABILITIES = ProviderCapabilities(
    tools=True,
    structured_output=True,
    reasoning_effort=True,
    context_window=1_050_000,
)
_ANTHROPIC_LARGE_CAPABILITIES = ProviderCapabilities(
    tools=True,
    context_window=1_000_000,
    max_output_tokens=128_000,
)
_ANTHROPIC_HAIKU_CAPABILITIES = ProviderCapabilities(
    tools=True,
    context_window=200_000,
    max_output_tokens=64_000,
)

INITIAL_MODEL_CATALOG: tuple[ModelCatalogSeed, ...] = (
    ModelCatalogSeed(
        "pgpt",
        "gpt-5.4",
        "GPT-5.4",
        "gpt-5.4",
        True,
        10,
        _PRODUCT_CONTRACT,
        capabilities=_PGPT_CAPABILITIES,
    ),
    ModelCatalogSeed(
        "pgpt",
        "gpt-5.4-mini",
        "GPT-5.4-mini",
        "gpt-5.4-mini",
        False,
        20,
        _PRODUCT_CONTRACT,
        capabilities=_PGPT_MINI_CAPABILITIES,
    ),
    ModelCatalogSeed(
        "codex",
        "gpt-5.5",
        "GPT-5.5",
        "gpt-5.5",
        True,
        10,
        _PRODUCT_CONTRACT,
        capabilities=_CODEX_TEXT_CAPABILITIES,
    ),
    ModelCatalogSeed(
        "codex",
        "gpt-5.4",
        "GPT-5.4",
        "gpt-5.4",
        False,
        20,
        _PRODUCT_CONTRACT,
        capabilities=_CODEX_TEXT_CAPABILITIES,
    ),
    ModelCatalogSeed(
        "google",
        "gemini-3.1-pro",
        "Gemini-3.1-Pro",
        "gemini-3.1-pro",
        True,
        10,
        _PRODUCT_CONTRACT,
        capabilities=_GOOGLE_CAPABILITIES,
    ),
    ModelCatalogSeed(
        "google",
        "gemini-3.5-flash",
        "Gemini-3.5-flash",
        "gemini-3.5-flash",
        False,
        20,
        _PRODUCT_CONTRACT,
        capabilities=_GOOGLE_CAPABILITIES,
    ),
    ModelCatalogSeed(
        "openai",
        "gpt-5.6-sol",
        "GPT-5.6-Sol",
        "gpt-5.6-sol",
        True,
        10,
        _OFFICIAL_2026_07_11,
        capabilities=_OPENAI_CAPABILITIES,
    ),
    ModelCatalogSeed(
        "openai",
        "gpt-5.6-terra",
        "GPT-5.6-Terra",
        "gpt-5.6-terra",
        False,
        20,
        _OFFICIAL_2026_07_11,
        capabilities=_OPENAI_CAPABILITIES,
    ),
    ModelCatalogSeed(
        "openai",
        "gpt-5.6-luna",
        "GPT-5.6-Luna",
        "gpt-5.6-luna",
        False,
        30,
        _OFFICIAL_2026_07_11,
        capabilities=_OPENAI_CAPABILITIES,
    ),
    ModelCatalogSeed(
        "anthropic",
        "claude-opus-4-8",
        "Claude Opus 4.8",
        "claude-opus-4-8",
        False,
        10,
        _OFFICIAL_2026_07_11,
        capabilities=_ANTHROPIC_LARGE_CAPABILITIES,
    ),
    ModelCatalogSeed(
        "anthropic",
        "claude-sonnet-5",
        "Claude Sonnet 5",
        "claude-sonnet-5",
        True,
        20,
        _OFFICIAL_2026_07_11,
        capabilities=_ANTHROPIC_LARGE_CAPABILITIES,
    ),
    ModelCatalogSeed(
        "anthropic",
        "claude-haiku-4-5",
        "Claude Haiku 4.5",
        "claude-haiku-4-5",
        False,
        30,
        _OFFICIAL_2026_07_11,
        capabilities=_ANTHROPIC_HAIKU_CAPABILITIES,
    ),
)


def validate_catalog(items: Iterable[ModelCatalogSeed]) -> None:
    seen: set[tuple[str, str]] = set()
    defaults: dict[str, int] = {}
    for item in items:
        key = (item.provider_id, item.model_key)
        if key in seen:
            raise ValueError(f"Duplicate model catalog key: {key!r}")
        seen.add(key)
        if item.is_default:
            defaults[item.provider_id] = defaults.get(item.provider_id, 0) + 1

    providers = {provider_id for provider_id, _ in seen}
    invalid = sorted(provider for provider in providers if defaults.get(provider) != 1)
    if invalid:
        raise ValueError(
            f"Each seeded provider needs exactly one default model: {invalid}"
        )


def initial_model_catalog(
    provider_id: str | None = None,
) -> tuple[ModelCatalogSeed, ...]:
    if provider_id is None:
        return INITIAL_MODEL_CATALOG
    return tuple(
        item for item in INITIAL_MODEL_CATALOG if item.provider_id == provider_id
    )


validate_catalog(INITIAL_MODEL_CATALOG)
