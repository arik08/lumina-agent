from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

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

    provider_id = "mock"
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
        title_requested = any(
            message.role == "system"
            and message.content
            and "LUMINA_SESSION_TITLE_JSON_V1" in message.content
            for message in request.messages
        )
        if title_requested:
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
