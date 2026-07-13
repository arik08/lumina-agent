"""Model-aware token estimation for user-visible Artifact content."""

from __future__ import annotations

from functools import lru_cache
from typing import Any


_DEFAULT_ENCODING = "o200k_base"
_LEGACY_OPENAI_ENCODING = "cl100k_base"


@lru_cache(maxsize=8)
def _get_encoding(encoding_name: str) -> Any | None:
    try:
        import tiktoken
    except Exception:
        return None
    try:
        return tiktoken.get_encoding(encoding_name)
    except Exception:
        return None


def _encoding_name_for_model(model: str | None) -> str:
    normalized = (model or "").strip().lower().rsplit("/", 1)[-1]
    if normalized.startswith(("gpt-3.5", "gpt-4-", "gpt-4-turbo")):
        return _LEGACY_OPENAI_ENCODING
    return _DEFAULT_ENCODING


def estimate_tokens(text: str, *, model: str | None = None) -> int:
    """Estimate document tokens with the model-family tokenizer when available."""
    if not text:
        return 0
    encoding = _get_encoding(_encoding_name_for_model(model))
    if encoding is not None:
        try:
            return max(1, len(encoding.encode(text)))
        except Exception:
            pass
    return max(1, (len(text) + 3) // 4)
