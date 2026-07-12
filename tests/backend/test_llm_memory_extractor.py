from collections.abc import AsyncIterator
import json

import pytest

from lumina.memories.service import (
    MemorySourceMessage,
    extract_memory_candidates_with_llm,
)
from lumina.providers.types import (
    ProviderCapabilities,
    ProviderEvent,
    ProviderRequest,
)


class _MemoryProvider:
    provider_id = "test"
    capabilities = ProviderCapabilities(structured_output=True)

    def __init__(self, response: str) -> None:
        self.response = response
        self.request: ProviderRequest | None = None

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.request = request
        yield ProviderEvent(type="text_delta", text=self.response)
        yield ProviderEvent(type="completed", stop_reason="stop")


@pytest.mark.asyncio
async def test_llm_memory_extractor_keeps_name_and_discards_remember_command() -> None:
    provider = _MemoryProvider(
        json.dumps(
            {
                "candidates": [
                    {
                        "category": "user_identity",
                        "fact": "user name: 오명철",
                        "displayText": "사용자 이름: 오명철",
                        "confidence": 0.99,
                        "conflictKey": "user_name",
                        "sourceMessageIds": ["message-1"],
                    }
                ]
            },
            ensure_ascii=False,
        )
    )

    candidates = await extract_memory_candidates_with_llm(
        provider,
        model="memory-test-model",
        messages=(
            MemorySourceMessage(
                id="message-1",
                run_id="run-1",
                text="내 이름은 오명철이야. 기억해",
            ),
        ),
    )

    assert len(candidates) == 1
    assert candidates[0].category == "user_identity"
    assert candidates[0].fact == "user name: 오명철"
    assert candidates[0].display_text == "사용자 이름: 오명철"
    assert candidates[0].conflict_key == "user_name"
    assert candidates[0].source_message_ids == ("message-1",)
    assert provider.request is not None
    assert provider.request.response_format is not None
    assert provider.request.temperature is None
    assert provider.request.metadata == {"purpose": "user_memory_extraction"}


@pytest.mark.asyncio
async def test_llm_memory_extractor_rejects_unknown_source_ids() -> None:
    provider = _MemoryProvider(
        json.dumps(
            {
                "candidates": [
                    {
                        "category": "user_identity",
                        "fact": "user name: 오명철",
                        "displayText": "사용자 이름: 오명철",
                        "confidence": 0.99,
                        "conflictKey": "user_name",
                        "sourceMessageIds": ["assistant-message"],
                    }
                ]
            },
            ensure_ascii=False,
        )
    )

    candidates = await extract_memory_candidates_with_llm(
        provider,
        model="memory-test-model",
        messages=(
            MemorySourceMessage(
                id="message-1",
                run_id="run-1",
                text="내 이름은 오명철이야. 기억해",
            ),
        ),
    )

    assert candidates == ()
