from __future__ import annotations

from lumina.providers.usage import (
    derive_uncached_input_tokens,
    prompt_cache_hit_ratio,
)


def test_usage_partition_excludes_cache_reads_and_writes() -> None:
    assert derive_uncached_input_tokens(100, 60, 15) == 25
    assert derive_uncached_input_tokens(10, 20, 5) == 0
    assert derive_uncached_input_tokens(-1, -2, -3) == 0


def test_prompt_cache_hit_ratio_counts_cache_writes_as_misses() -> None:
    assert prompt_cache_hit_ratio(75, 110) == 75 / 110
    assert prompt_cache_hit_ratio(0, 0) == 0.0
    assert prompt_cache_hit_ratio(-1, 20) == 0.0
    assert prompt_cache_hit_ratio(30, 20) == 1.0
