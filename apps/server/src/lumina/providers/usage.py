from __future__ import annotations


def derive_uncached_input_tokens(
    input_tokens: int,
    cached_input_tokens: int,
    cache_write_tokens: int = 0,
) -> int:
    """Return the input partition that was neither read nor written as cache."""

    return max(
        0,
        max(0, input_tokens) - max(0, cached_input_tokens) - max(0, cache_write_tokens),
    )


def prompt_cache_hit_ratio(
    cached_input_tokens: int,
    input_tokens: int,
) -> float:
    """Measure the share of reported input tokens read from prompt cache."""

    cached = max(0, cached_input_tokens)
    total = max(0, input_tokens)
    return min(cached, total) / total if total else 0.0
