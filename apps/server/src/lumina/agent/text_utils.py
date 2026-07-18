"""Bounded text helpers shared by prompt and Tool-result preparation."""

from __future__ import annotations


def _bounded_text(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit < 200:
        return value[:limit]
    marker = "\n\n[... context truncated ...]\n\n"
    content_budget = limit - len(marker)
    tail = min(content_budget // 3, 40_000)
    head = content_budget - tail
    return value[:head] + marker + value[-tail:]
