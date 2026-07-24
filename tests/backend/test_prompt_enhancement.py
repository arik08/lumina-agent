from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from lumina.api.schemas import MessageReferenceInput
from lumina.prompt_enhancement import (
    MAX_PROMPT_ENHANCEMENT_OUTPUT_TOKENS,
    enhance_prompt,
    mask_prompt_references,
    restore_prompt_references,
)
from lumina.providers import ProviderCapabilities, ProviderEvent, ProviderRequest


class _PromptEnhancementProvider:
    provider_id = "test"
    capabilities = ProviderCapabilities(reasoning_effort=True)

    def __init__(self, response: str) -> None:
        self.response = response
        self.request: ProviderRequest | None = None

    async def stream(
        self, request: ProviderRequest
    ) -> AsyncIterator[ProviderEvent]:
        self.request = request
        yield ProviderEvent(type="text_delta", text=self.response)
        yield ProviderEvent(type="completed", stop_reason="stop")


@pytest.mark.asyncio
async def test_prompt_enhancement_is_one_low_effort_tool_free_call() -> None:
    source = "$skill:insane-search로 철강사를 비교해줘"
    token = "$skill:insane-search"
    placeholder = "<<LUMINA_REFERENCE_001>>"
    provider = _PromptEnhancementProvider(
        f"{placeholder}를 활용해 철강사를 수치와 출처를 포함하여 비교해 주세요."
    )

    enhanced = await enhance_prompt(
        provider=provider,
        model="fast-model",
        text=source,
        options=("evidence",),
        references=(
            MessageReferenceInput(
                kind="skill",
                reference_id="skill-id",
                token_start=0,
                token_end=len(token),
            ),
        ),
    )

    assert enhanced.startswith(token)
    assert provider.request is not None
    assert provider.request.tools == ()
    assert provider.request.effort == "low"
    assert (
        provider.request.max_output_tokens
        == MAX_PROMPT_ENHANCEMENT_OUTPUT_TOKENS
    )
    assert provider.request.metadata == {"purpose": "prompt_enhancement"}
    assert "research facts, browse, call tools" in (
        provider.request.messages[0].content or ""
    )
    user_prompt = provider.request.messages[1].content or ""
    assert "Add concise requirements for evidence" in user_prompt
    assert "Clarify and organize the objective" not in user_prompt


@pytest.mark.asyncio
async def test_prompt_enhancement_defaults_unqualified_report_to_html() -> None:
    provider = _PromptEnhancementProvider("HTML 보고서를 작성해 주세요.")

    await enhance_prompt(
        provider=provider,
        model="fast-model",
        text="시장 분석 보고서를 작성해줘",
        options=("output_format",),
        references=(),
    )

    assert provider.request is not None
    system_prompt = provider.request.messages[0].content or ""
    assert "unqualified Korean '보고서'" in system_prompt
    assert "as an HTML report" in system_prompt
    assert "never replace an explicitly requested output format" in system_prompt


@pytest.mark.asyncio
async def test_prompt_enhancement_accepts_only_a_custom_instruction() -> None:
    provider = _PromptEnhancementProvider("핵심만 간단히 비교해 주세요.")

    await enhance_prompt(
        provider=provider,
        model="fast-model",
        text="철강사를 비교해줘",
        options=(),
        custom_instruction="핵심만 간단히 정리해줘",
        references=(),
    )

    assert provider.request is not None
    user_prompt = provider.request.messages[1].content or ""
    assert "No preset edits selected" in user_prompt
    assert "핵심만 간단히 정리해줘" in user_prompt


@pytest.mark.asyncio
async def test_prompt_enhancement_rejects_changed_reference_placeholder() -> None:
    provider = _PromptEnhancementProvider("참조 없이 다시 작성했습니다.")

    with pytest.raises(ValueError, match="reference_placeholder_changed"):
        await enhance_prompt(
            provider=provider,
            model="fast-model",
            text="$mcp:comtrade로 분석해줘",
            options=("structure",),
            references=(
                MessageReferenceInput(
                    kind="mcp",
                    reference_id="mcp-id",
                    token_start=0,
                    token_end=len("$mcp:comtrade"),
                ),
            ),
        )


def test_prompt_reference_masking_rejects_overlapping_ranges() -> None:
    references = (
        MessageReferenceInput(
            kind="skill",
            reference_id="skill-id",
            token_start=0,
            token_end=8,
        ),
        MessageReferenceInput(
            kind="mcp",
            reference_id="mcp-id",
            token_start=4,
            token_end=12,
        ),
    )

    with pytest.raises(ValueError, match="overlapping_reference_range"):
        mask_prompt_references("abcdefghijkl", references)


def test_prompt_reference_masking_round_trips_exact_text() -> None:
    source = "@자료와 $mcp:comtrade를 사용해줘"
    references = (
        MessageReferenceInput(
            kind="file",
            reference_id="file-id",
            token_start=0,
            token_end=len("@자료"),
        ),
        MessageReferenceInput(
            kind="mcp",
            reference_id="mcp-id",
            token_start=5,
            token_end=5 + len("$mcp:comtrade"),
        ),
    )

    masked, replacements = mask_prompt_references(source, references)

    assert restore_prompt_references(masked, replacements) == source
