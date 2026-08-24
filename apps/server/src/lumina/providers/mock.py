from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from .constants import MOCK_PROVIDER_ID
from .types import (
    ProviderCapabilities,
    ProviderEvent,
    ProviderRequest,
    ProviderUsage,
)


@dataclass(frozen=True, slots=True)
class MockToolCall:
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    call_id: str = "mock_call_1"


class MockProvider:
    """A deterministic provider used by local development and contract tests."""

    provider_id = MOCK_PROVIDER_ID
    capabilities = ProviderCapabilities(
        tools=True,
        structured_output=True,
        reasoning_effort=True,
    )

    def __init__(
        self,
        *,
        text_chunks: tuple[str, ...] = ("Mock response.",),
        tool_call: MockToolCall | None = None,
        tool_calls: tuple[MockToolCall, ...] = (),
        usage: ProviderUsage | None = None,
    ) -> None:
        if tool_call is not None and tool_calls:
            raise ValueError("Use either tool_call or tool_calls, not both")
        self._text_chunks = text_chunks
        self._tool_calls = (tool_call,) if tool_call is not None else tool_calls
        self._usage = usage or ProviderUsage(
            input_tokens=8,
            uncached_input_tokens=8,
            output_tokens=sum(len(chunk) for chunk in text_chunks),
            raw={"provider": "mock"},
        )

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        knowledge_tag_payload = _knowledge_tag_payload(request)
        title_requested = any(
            message.role == "system"
            and message.content
            and "LUMINA_SESSION_TITLE_JSON_V1" in message.content
            for message in request.messages
        )
        if knowledge_tag_payload is not None:
            yield ProviderEvent(
                type="text_delta",
                text=json.dumps(
                    knowledge_tag_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        elif title_requested:
            user_text = next(
                (
                    message.content
                    for message in reversed(request.messages)
                    if message.role == "user" and message.content
                ),
                "새 대화",
            )
            normalized = " ".join(user_text.split())
            title = f"{normalized[:48].rstrip()} 요약"
            yield ProviderEvent(
                type="text_delta",
                text=json.dumps(
                    {"session_title": title[:60]},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n",
            )
        if knowledge_tag_payload is None:
            for chunk in self._text_chunks:
                await asyncio.sleep(0)
                yield ProviderEvent(type="text_delta", text=chunk)

        stop_reason = "stop"
        if self._tool_calls:
            stop_reason = "tool_calls"
        for tool_call in self._tool_calls:
            arguments_json = json.dumps(
                tool_call.arguments,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            yield ProviderEvent(
                type="tool_call_started",
                tool_call_id=tool_call.call_id,
                tool_name=tool_call.name,
            )
            yield ProviderEvent(
                type="tool_call_delta",
                tool_call_id=tool_call.call_id,
                tool_name=tool_call.name,
                arguments_delta=arguments_json,
            )
            yield ProviderEvent(
                type="tool_call_completed",
                tool_call_id=tool_call.call_id,
                tool_name=tool_call.name,
                arguments_json=arguments_json,
            )

        yield ProviderEvent(type="usage", usage=self._usage)
        yield ProviderEvent(type="completed", stop_reason=stop_reason)


def _knowledge_tag_payload(request: ProviderRequest) -> dict[str, object] | None:
    if request.metadata.get("purpose") != "knowledge_document_batch_tagging":
        return None
    response_format = request.response_format
    if not isinstance(response_format, Mapping):
        return None
    json_schema = response_format.get("json_schema")
    if not isinstance(json_schema, Mapping):
        return None
    schema = json_schema.get("schema")
    if not isinstance(schema, Mapping):
        return None
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return None
    documents_schema = properties.get("documents")
    if not isinstance(documents_schema, Mapping):
        return None
    document_count = documents_schema.get("minItems")
    if not isinstance(document_count, int) or document_count < 1:
        return None
    item_schema = documents_schema.get("items")
    item_properties = (
        item_schema.get("properties") if isinstance(item_schema, Mapping) else None
    )
    candidate_indexes_schema = (
        item_properties.get("candidateIndexes")
        if isinstance(item_properties, Mapping)
        else None
    )
    candidate_item_schema = (
        candidate_indexes_schema.get("items")
        if isinstance(candidate_indexes_schema, Mapping)
        else None
    )
    has_candidates = (
        isinstance(candidate_item_schema, Mapping)
        and isinstance(candidate_item_schema.get("maximum"), int)
    )
    return {
        "documents": [
            {
                "documentIndex": index,
                "candidateIndexes": [0] if has_candidates else [],
                "newTags": []
                if has_candidates
                else [
                    {
                        "canonicalName": "AI 활용",
                        "scopeNote": "AI 적용 사례",
                        "aliases": ["인공지능 활용"],
                    },
                    {
                        "canonicalName": "업무 자동화",
                        "scopeNote": "업무 절차 자동화",
                        "aliases": ["프로세스 자동화"],
                    },
                    {
                        "canonicalName": "데이터 분석",
                        "scopeNote": "데이터 기반 분석",
                        "aliases": ["데이터 애널리틱스"],
                    },
                ],
            }
            for index in range(document_count)
        ]
    }
