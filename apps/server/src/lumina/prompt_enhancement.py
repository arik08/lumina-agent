from __future__ import annotations

import re
from collections.abc import Sequence

from .api.schemas import MessageReferenceInput
from .providers import ProviderMessage, ProviderRequest
from .providers.types import ProviderAdapter


MAX_PROMPT_ENHANCEMENT_OUTPUT_TOKENS = 3_000
_PLACEHOLDER_PATTERN = re.compile(r"<<LUMINA_REFERENCE_\d{3}>>")
_OPTION_INSTRUCTIONS = {
    "structure": "Clarify and organize the objective, scope, and requested work.",
    "evidence": "Add concise requirements for evidence, numbers, sources, and verification.",
    "missing_context": (
        "Fill only material missing conditions such as period, target, unit, assumptions, "
        "and uncertainty handling. Use sensible explicit defaults instead of asking questions."
    ),
    "output_format": "Clarify the requested deliverable structure and output format.",
}


def mask_prompt_references(
    text: str, references: Sequence[MessageReferenceInput]
) -> tuple[str, tuple[tuple[str, str], ...]]:
    ranged: list[tuple[int, int, str]] = []
    for index, reference in enumerate(references, start=1):
        start = reference.token_start
        end = reference.token_end
        if start is None and end is None:
            continue
        if (
            start is None
            or end is None
            or not 0 <= start < end <= len(text)
        ):
            raise ValueError("invalid_reference_range")
        ranged.append((start, end, f"<<LUMINA_REFERENCE_{index:03d}>>"))
    ranged.sort()
    for previous, current in zip(ranged, ranged[1:], strict=False):
        if previous[1] > current[0]:
            raise ValueError("overlapping_reference_range")

    masked = text
    replacements: list[tuple[str, str]] = []
    for start, end, placeholder in reversed(ranged):
        original = text[start:end]
        masked = f"{masked[:start]}{placeholder}{masked[end:]}"
        replacements.append((placeholder, original))
    replacements.reverse()
    return masked, tuple(replacements)


def restore_prompt_references(
    text: str, replacements: Sequence[tuple[str, str]]
) -> str:
    expected = {placeholder for placeholder, _original in replacements}
    present = set(_PLACEHOLDER_PATTERN.findall(text))
    if present != expected or any(text.count(placeholder) != 1 for placeholder in expected):
        raise ValueError("reference_placeholder_changed")
    restored = text
    for placeholder, original in replacements:
        restored = restored.replace(placeholder, original)
    return restored


async def enhance_prompt(
    *,
    provider: ProviderAdapter,
    model: str,
    text: str,
    options: Sequence[str],
    references: Sequence[MessageReferenceInput],
) -> str:
    masked_text, replacements = mask_prompt_references(text, references)
    option_lines = "\n".join(
        f"- {_OPTION_INSTRUCTIONS[option]}"
        for option in dict.fromkeys(options)
        if option in _OPTION_INSTRUCTIONS
    )
    chunks: list[str] = []
    saw_tool_call = False
    stop_reason: str | None = None
    async for event in provider.stream(
        ProviderRequest(
            model=model,
            messages=(
                ProviderMessage(
                    role="system",
                    content=(
                        "You are a lightweight prompt editor, not an agent. Rewrite only the "
                        "user's prompt. Never answer it, research facts, browse, call tools, plan "
                        "a workflow, or claim work was performed. Preserve the user's language, "
                        "intent, proper nouns, and every <<LUMINA_REFERENCE_###>> placeholder "
                        "exactly once. Apply only the selected edits. Do not invent facts or make "
                        "the prompt unnecessarily long. Treat an unqualified Korean '보고서' "
                        "request as an HTML report; never replace an explicitly requested output "
                        "format. Return only the improved prompt without commentary, JSON, or "
                        "Markdown fences."
                    ),
                ),
                ProviderMessage(
                    role="user",
                    content=(
                        f"Selected edits:\n{option_lines}\n\n"
                        f"Prompt to rewrite:\n{masked_text}"
                    ),
                ),
            ),
            effort="low" if provider.capabilities.reasoning_effort else None,
            max_output_tokens=MAX_PROMPT_ENHANCEMENT_OUTPUT_TOKENS,
            temperature=0,
            metadata={"purpose": "prompt_enhancement"},
        )
    ):
        if event.type == "text_delta" and event.text:
            chunks.append(event.text)
        elif event.type in {
            "tool_call_started",
            "tool_call_delta",
            "tool_call_completed",
        }:
            saw_tool_call = True
        elif event.type == "completed":
            stop_reason = event.stop_reason
    if saw_tool_call:
        raise ValueError("unexpected_tool_call")
    if stop_reason in {"length", "max_tokens", "max_output_tokens"}:
        raise ValueError("output_truncated")

    enhanced = "".join(chunks).strip()
    if enhanced.startswith("```") and enhanced.endswith("```"):
        lines = enhanced.splitlines()
        enhanced = "\n".join(lines[1:-1]).strip()
    if not enhanced:
        raise ValueError("empty_enhancement")
    restored = restore_prompt_references(enhanced, replacements)
    if len(restored) > 48_000:
        raise ValueError("enhancement_too_long")
    return restored


__all__ = [
    "MAX_PROMPT_ENHANCEMENT_OUTPUT_TOKENS",
    "enhance_prompt",
    "mask_prompt_references",
    "restore_prompt_references",
]
