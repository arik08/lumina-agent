from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from .types import ProviderCapabilities

CATALOG_REVISION = "2026-07-15.1-pgpt-5.5-5.6"
CATALOG_VERIFIED_AT = date(2026, 7, 15)
PUBLIC_PRICING_VERSION = "public-list-2026-07-12"
DEFAULT_CONTEXT_COMPACTION_THRESHOLD = 0.75


@dataclass(frozen=True, slots=True)
class ModelTokenPricing:
    """USD list prices per one million tokens for a reviewed model."""

    input: float
    cached_input: float
    cache_write_input: float
    output: float
    long_context_threshold: int | None = None
    long_context_input: float | None = None
    long_context_cached_input: float | None = None
    long_context_cache_write_input: float | None = None
    long_context_output: float | None = None
    version: str = PUBLIC_PRICING_VERSION


@dataclass(frozen=True, slots=True)
class ModelOperationalProfile:
    provider_id: str
    model_reference: str
    context_window: int | None
    context_compaction_threshold: float | None
    token_pricing: ModelTokenPricing | None


@dataclass(frozen=True, slots=True)
class ModelCatalogSeed:
    """Schema for one complete model block.

    Add optional cross-model attributes here with a safe default, then override them
    only in model blocks that need a non-default value.
    """

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
    default_max_output_tokens: int | None = None
    output_token_step: int = 1_000
    context_compaction_threshold: float | None = None
    token_pricing: ModelTokenPricing | None = None
    catalog_revision: str = CATALOG_REVISION
    verified_at: date = CATALOG_VERIFIED_AT

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Adding a model means adding exactly one self-contained block below.
# Keep every model-specific capability, limit, threshold, and price in that block.
INITIAL_MODEL_CATALOG: tuple[ModelCatalogSeed, ...] = (
    ModelCatalogSeed(
        provider_id="pgpt",
        model_key="gpt-5.4",
        display_name="GPT-5.4",
        runtime_model_id="gpt-5.4",
        is_default=True,
        sort_order=10,
        source="product_contract:user",
        capabilities=ProviderCapabilities(
            tools=True,
            structured_output=True,
            reasoning_effort=True,
            context_window=1_050_000,
            max_output_tokens=128_000,
        ),
        default_max_output_tokens=42_000,
    ),
    ModelCatalogSeed(
        provider_id="pgpt",
        model_key="gpt-5.4-mini",
        display_name="GPT-5.4-mini",
        runtime_model_id="gpt-5.4-mini",
        is_default=False,
        sort_order=20,
        source="product_contract:user",
        capabilities=ProviderCapabilities(
            tools=True,
            structured_output=True,
            reasoning_effort=True,
            context_window=400_000,
            max_output_tokens=128_000,
        ),
        default_max_output_tokens=42_000,
    ),
    ModelCatalogSeed(
        provider_id="pgpt",
        model_key="gpt-5.5",
        display_name="GPT-5.5",
        runtime_model_id="gpt-5.5",
        is_default=False,
        sort_order=30,
        source="product_contract:user",
        capabilities=ProviderCapabilities(
            tools=True,
            structured_output=True,
            reasoning_effort=True,
            context_window=1_050_000,
            max_output_tokens=128_000,
        ),
        default_max_output_tokens=42_000,
    ),
    ModelCatalogSeed(
        provider_id="pgpt",
        model_key="gpt-5.6-sol",
        display_name="GPT-5.6-Sol",
        runtime_model_id="gpt-5.6-sol",
        is_default=False,
        sort_order=40,
        source="product_contract:user",
        capabilities=ProviderCapabilities(
            tools=True,
            structured_output=True,
            reasoning_effort=True,
            context_window=1_050_000,
            max_output_tokens=128_000,
        ),
        default_max_output_tokens=42_000,
    ),
    ModelCatalogSeed(
        provider_id="pgpt",
        model_key="gpt-5.6-terra",
        display_name="GPT-5.6-Terra",
        runtime_model_id="gpt-5.6-terra",
        is_default=False,
        sort_order=50,
        source="product_contract:user",
        capabilities=ProviderCapabilities(
            tools=True,
            structured_output=True,
            reasoning_effort=True,
            context_window=1_050_000,
            max_output_tokens=128_000,
        ),
        default_max_output_tokens=42_000,
    ),
    ModelCatalogSeed(
        provider_id="pgpt",
        model_key="gpt-5.6-luna",
        display_name="GPT-5.6-Luna",
        runtime_model_id="gpt-5.6-luna",
        is_default=False,
        sort_order=60,
        source="product_contract:user",
        capabilities=ProviderCapabilities(
            tools=True,
            structured_output=True,
            reasoning_effort=True,
            context_window=1_050_000,
            max_output_tokens=128_000,
        ),
        default_max_output_tokens=42_000,
    ),
    ModelCatalogSeed(
        provider_id="codex",
        model_key="gpt-5.5",
        display_name="GPT-5.5",
        runtime_model_id="gpt-5.5",
        is_default=True,
        sort_order=40,
        source="product_contract:user",
        capabilities=ProviderCapabilities(
            tools=True,
            structured_output=True,
            reasoning_effort=True,
            context_window=272_000,
        ),
        context_compaction_threshold=0.85,
        token_pricing=ModelTokenPricing(
            input=5.0,
            cached_input=0.5,
            cache_write_input=5.0,
            output=30.0,
            long_context_threshold=272_000,
            long_context_input=10.0,
            long_context_cached_input=1.0,
            long_context_cache_write_input=10.0,
            long_context_output=45.0,
        ),
    ),
    ModelCatalogSeed(
        provider_id="codex",
        model_key="gpt-5.4",
        display_name="GPT-5.4",
        runtime_model_id="gpt-5.4",
        is_default=False,
        sort_order=50,
        source="product_contract:user",
        capabilities=ProviderCapabilities(
            tools=True,
            structured_output=True,
            reasoning_effort=True,
            context_window=272_000,
        ),
        context_compaction_threshold=0.85,
        token_pricing=ModelTokenPricing(
            input=2.5,
            cached_input=0.25,
            cache_write_input=2.5,
            output=15.0,
            long_context_threshold=272_000,
            long_context_input=5.0,
            long_context_cached_input=0.5,
            long_context_cache_write_input=5.0,
            long_context_output=22.5,
        ),
    ),
    ModelCatalogSeed(
        provider_id="google",
        model_key="gemini-3.1-pro",
        display_name="Gemini-3.1-Pro",
        runtime_model_id="gemini-3.1-pro",
        is_default=True,
        sort_order=10,
        source="product_contract:user",
        capabilities=ProviderCapabilities(
            tools=True,
            structured_output=True,
            context_window=1_000_000,
            max_output_tokens=64_000,
        ),
        token_pricing=ModelTokenPricing(
            input=2.0,
            cached_input=0.2,
            cache_write_input=2.0,
            output=12.0,
            long_context_threshold=200_000,
            long_context_input=4.0,
            long_context_cached_input=0.4,
            long_context_cache_write_input=4.0,
            long_context_output=18.0,
        ),
    ),
    ModelCatalogSeed(
        provider_id="google",
        model_key="gemini-3.5-flash",
        display_name="Gemini-3.5-flash",
        runtime_model_id="gemini-3.5-flash",
        is_default=False,
        sort_order=20,
        source="product_contract:user",
        capabilities=ProviderCapabilities(
            tools=True,
            structured_output=True,
            context_window=1_000_000,
            max_output_tokens=64_000,
        ),
        token_pricing=ModelTokenPricing(
            input=1.5,
            cached_input=0.15,
            cache_write_input=1.5,
            output=9.0,
        ),
    ),
    ModelCatalogSeed(
        provider_id="openai",
        model_key="gpt-5.6-sol",
        display_name="GPT-5.6-Sol",
        runtime_model_id="gpt-5.6-sol",
        is_default=True,
        sort_order=10,
        source="official_docs:2026-07-11",
        capabilities=ProviderCapabilities(
            tools=True,
            structured_output=True,
            reasoning_effort=True,
            context_window=1_050_000,
        ),
        token_pricing=ModelTokenPricing(
            input=5.0,
            cached_input=0.5,
            cache_write_input=6.25,
            output=30.0,
            long_context_threshold=272_000,
            long_context_input=10.0,
            long_context_cached_input=1.0,
            long_context_cache_write_input=12.5,
            long_context_output=45.0,
        ),
    ),
    ModelCatalogSeed(
        provider_id="openai",
        model_key="gpt-5.6-terra",
        display_name="GPT-5.6-Terra",
        runtime_model_id="gpt-5.6-terra",
        is_default=False,
        sort_order=20,
        source="official_docs:2026-07-11",
        capabilities=ProviderCapabilities(
            tools=True,
            structured_output=True,
            reasoning_effort=True,
            context_window=1_050_000,
        ),
        token_pricing=ModelTokenPricing(
            input=2.5,
            cached_input=0.25,
            cache_write_input=3.125,
            output=15.0,
            long_context_threshold=272_000,
            long_context_input=5.0,
            long_context_cached_input=0.5,
            long_context_cache_write_input=6.25,
            long_context_output=22.5,
        ),
    ),
    ModelCatalogSeed(
        provider_id="openai",
        model_key="gpt-5.6-luna",
        display_name="GPT-5.6-Luna",
        runtime_model_id="gpt-5.6-luna",
        is_default=False,
        sort_order=30,
        source="official_docs:2026-07-11",
        capabilities=ProviderCapabilities(
            tools=True,
            structured_output=True,
            reasoning_effort=True,
            context_window=1_050_000,
        ),
        token_pricing=ModelTokenPricing(
            input=1.0,
            cached_input=0.1,
            cache_write_input=1.25,
            output=6.0,
            long_context_threshold=272_000,
            long_context_input=2.0,
            long_context_cached_input=0.2,
            long_context_cache_write_input=2.5,
            long_context_output=9.0,
        ),
    ),
    ModelCatalogSeed(
        provider_id="anthropic",
        model_key="claude-opus-4-8",
        display_name="Claude Opus 4.8",
        runtime_model_id="claude-opus-4-8",
        is_default=False,
        sort_order=10,
        source="official_docs:2026-07-11",
        capabilities=ProviderCapabilities(
            tools=True,
            context_window=1_000_000,
            max_output_tokens=128_000,
        ),
        token_pricing=ModelTokenPricing(
            input=5.0,
            cached_input=0.5,
            cache_write_input=6.25,
            output=25.0,
        ),
    ),
    ModelCatalogSeed(
        provider_id="anthropic",
        model_key="claude-sonnet-5",
        display_name="Claude Sonnet 5",
        runtime_model_id="claude-sonnet-5",
        is_default=True,
        sort_order=20,
        source="official_docs:2026-07-11",
        capabilities=ProviderCapabilities(
            tools=True,
            context_window=1_000_000,
            max_output_tokens=128_000,
        ),
        token_pricing=ModelTokenPricing(
            input=2.0,
            cached_input=0.2,
            cache_write_input=2.5,
            output=10.0,
        ),
    ),
    ModelCatalogSeed(
        provider_id="anthropic",
        model_key="claude-haiku-4-5",
        display_name="Claude Haiku 4.5",
        runtime_model_id="claude-haiku-4-5",
        is_default=False,
        sort_order=30,
        source="official_docs:2026-07-11",
        capabilities=ProviderCapabilities(
            tools=True,
            context_window=200_000,
            max_output_tokens=64_000,
        ),
        token_pricing=ModelTokenPricing(
            input=1.0,
            cached_input=0.1,
            cache_write_input=1.25,
            output=5.0,
        ),
    ),
)

EXTRA_MODEL_OPERATIONAL_PROFILES: tuple[ModelOperationalProfile, ...] = tuple(
    ModelOperationalProfile(
        provider_id="codex",
        model_reference=item.model_key,
        context_window=272_000,
        context_compaction_threshold=0.85,
        token_pricing=item.token_pricing,
    )
    for item in INITIAL_MODEL_CATALOG
    if item.provider_id == "openai" and item.model_key.startswith("gpt-5.6-")
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
        hard_max = item.capabilities.max_output_tokens
        default_max = item.default_max_output_tokens
        if hard_max is not None and hard_max < 1:
            raise ValueError(f"Model hard output limit must be positive: {key!r}")
        if default_max is not None and default_max < 1:
            raise ValueError(f"Model default output limit must be positive: {key!r}")
        if default_max is not None and hard_max is None:
            raise ValueError(f"Model default output limit needs a hard limit: {key!r}")
        if default_max is not None and hard_max is not None and default_max > hard_max:
            raise ValueError(f"Model default output limit exceeds hard limit: {key!r}")
        if item.output_token_step < 1:
            raise ValueError(f"Model output token step must be positive: {key!r}")
        threshold = item.context_compaction_threshold
        if threshold is not None and not 0 < threshold <= 1:
            raise ValueError(f"Model compaction threshold must be in (0, 1]: {key!r}")
        pricing = item.token_pricing
        if pricing is not None:
            rates = (
                pricing.input,
                pricing.cached_input,
                pricing.cache_write_input,
                pricing.output,
            )
            if any(rate < 0 for rate in rates):
                raise ValueError(f"Model token pricing cannot be negative: {key!r}")
            long_rates = (
                pricing.long_context_input,
                pricing.long_context_cached_input,
                pricing.long_context_cache_write_input,
                pricing.long_context_output,
            )
            if pricing.long_context_threshold is None:
                if any(rate is not None for rate in long_rates):
                    raise ValueError(f"Long-context prices need a threshold: {key!r}")
            elif pricing.long_context_threshold < 1 or any(
                rate is None or rate < 0 for rate in long_rates
            ):
                raise ValueError(f"Long-context pricing is incomplete: {key!r}")

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


def catalog_model(provider_id: str, model_reference: str) -> ModelCatalogSeed | None:
    normalized = model_reference.casefold()
    return next(
        (
            item
            for item in initial_model_catalog(provider_id)
            if normalized
            in {
                item.model_key.casefold(),
                item.runtime_model_id.casefold(),
                *(alias.casefold() for alias in item.aliases),
            }
        ),
        None,
    )


def estimate_model_cost_parts(
    provider_id: str,
    model_reference: str,
    *,
    input_tokens: int,
    cached_input_tokens: int,
    cache_write_tokens: int,
    output_tokens: int,
) -> dict[str, float] | None:
    profile = model_operational_profile(provider_id, model_reference)
    pricing = profile.token_pricing if profile is not None else None
    if pricing is None:
        return None

    uncached_input_tokens = max(
        0, input_tokens - cached_input_tokens - cache_write_tokens
    )
    input_rate = pricing.input
    cached_rate = pricing.cached_input
    cache_write_rate = pricing.cache_write_input
    output_rate = pricing.output
    if (
        pricing.long_context_threshold is not None
        and input_tokens > pricing.long_context_threshold
    ):
        input_rate = pricing.long_context_input or 0.0
        cached_rate = pricing.long_context_cached_input or 0.0
        cache_write_rate = pricing.long_context_cache_write_input or 0.0
        output_rate = pricing.long_context_output or 0.0
    uncached_input_cost = uncached_input_tokens * input_rate / 1_000_000
    cached_input_cost = cached_input_tokens * cached_rate / 1_000_000
    cache_write_input_cost = cache_write_tokens * cache_write_rate / 1_000_000
    output_cost = output_tokens * output_rate / 1_000_000
    return {
        "uncached_input": uncached_input_cost,
        "cached_input": cached_input_cost,
        "cache_write_input": cache_write_input_cost,
        "input": uncached_input_cost + cached_input_cost + cache_write_input_cost,
        "output": output_cost,
        "total": (
            uncached_input_cost
            + cached_input_cost
            + cache_write_input_cost
            + output_cost
        ),
    }


def model_operational_profile(
    provider_id: str, model_reference: str
) -> ModelOperationalProfile | None:
    catalog_entry = catalog_model(provider_id, model_reference)
    if catalog_entry is not None:
        return ModelOperationalProfile(
            provider_id=catalog_entry.provider_id,
            model_reference=catalog_entry.model_key,
            context_window=catalog_entry.capabilities.context_window,
            context_compaction_threshold=(catalog_entry.context_compaction_threshold),
            token_pricing=catalog_entry.token_pricing,
        )
    normalized = model_reference.casefold()
    return next(
        (
            profile
            for profile in EXTRA_MODEL_OPERATIONAL_PROFILES
            if profile.provider_id == provider_id
            and profile.model_reference.casefold() == normalized
        ),
        None,
    )


def default_catalog_model(provider_id: str) -> ModelCatalogSeed:
    return next(item for item in initial_model_catalog(provider_id) if item.is_default)


def application_default_execution(environment: str) -> tuple[str, str, str]:
    if environment != "production":
        return "mock", "mock-agent", "medium"
    model = default_catalog_model("pgpt")
    return model.provider_id, model.model_key, "medium"


validate_catalog(INITIAL_MODEL_CATALOG)
