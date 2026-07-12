from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from lumina.http_client import TrustManager, TrustProfile, create_http_client

from ..errors import ProviderConfigurationError, ProviderRequestError
from ..http import http_status_error, network_error, validate_http_base_url
from ..types import (
    ProviderCapabilities,
    ProviderEvent,
    ProviderRequest,
    ProviderUsage,
)


DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_OUTPUT_TOKENS = 4_096


@dataclass(slots=True)
class _ToolState:
    index: int
    call_id: str
    name: str | None
    arguments: str = ""
    completed: bool = False


class AnthropicMessagesAdapter:
    provider_id = "anthropic"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_ANTHROPIC_BASE_URL,
        client: httpx.AsyncClient | None = None,
        trust_profile: TrustProfile | None = None,
    ) -> None:
        secret = api_key.strip()
        if not secret:
            raise ProviderConfigurationError(
                "Anthropic credentials are not configured; ANTHROPIC_API_KEY is required."
            )
        self.base_url = validate_http_base_url(base_url, "Anthropic")
        self._api_key = secret
        self._client = client
        self._trust_profile = trust_profile

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        client = self._client
        owns_client = client is None
        if client is None:
            profile = self._trust_profile or TrustManager().initialize()
            client = create_http_client(profile)

        tools: dict[int, _ToolState] = {}
        raw_usage: dict[str, Any] = {}
        stop_reason: str | None = None
        try:
            async with client.stream(
                "POST",
                f"{self.base_url}/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                },
                json=build_anthropic_payload(request),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    event = _event_from_line(line)
                    if event is None:
                        continue
                    event_type = event.get("type")
                    if event_type == "error":
                        raise _stream_error(event)
                    if event_type == "message_start":
                        message = event.get("message")
                        if isinstance(message, Mapping):
                            _merge_usage(raw_usage, message.get("usage"))
                        continue
                    if event_type == "content_block_start":
                        index = _integer(event.get("index"))
                        block = event.get("content_block")
                        if not isinstance(block, Mapping):
                            continue
                        if block.get("type") == "text":
                            text = block.get("text")
                            if isinstance(text, str) and text:
                                yield ProviderEvent(type="text_delta", text=text)
                            continue
                        if block.get("type") != "tool_use":
                            continue
                        state = _tool_state(index, block, tools)
                        yield ProviderEvent(
                            type="tool_call_started",
                            tool_call_id=state.call_id,
                            tool_name=state.name,
                        )
                        initial_input = block.get("input")
                        if isinstance(initial_input, Mapping) and initial_input:
                            state.arguments = _json_text(initial_input)
                            yield ProviderEvent(
                                type="tool_call_delta",
                                tool_call_id=state.call_id,
                                tool_name=state.name,
                                arguments_delta=state.arguments,
                            )
                        continue
                    if event_type == "content_block_delta":
                        index = _integer(event.get("index"))
                        delta = event.get("delta")
                        if not isinstance(delta, Mapping):
                            continue
                        if delta.get("type") == "text_delta":
                            text = delta.get("text")
                            if isinstance(text, str) and text:
                                yield ProviderEvent(type="text_delta", text=text)
                            continue
                        if delta.get("type") != "input_json_delta":
                            continue
                        active_state = tools.get(index)
                        partial = delta.get("partial_json")
                        if (
                            active_state is not None
                            and isinstance(partial, str)
                            and partial
                        ):
                            active_state.arguments += partial
                            yield ProviderEvent(
                                type="tool_call_delta",
                                tool_call_id=active_state.call_id,
                                tool_name=active_state.name,
                                arguments_delta=partial,
                            )
                        continue
                    if event_type == "content_block_stop":
                        active_state = tools.get(_integer(event.get("index")))
                        if active_state is not None and not active_state.completed:
                            active_state.completed = True
                            yield _completed_tool(active_state)
                        continue
                    if event_type == "message_delta":
                        delta = event.get("delta")
                        if isinstance(delta, Mapping) and delta.get("stop_reason"):
                            stop_reason = str(delta["stop_reason"])
                        _merge_usage(raw_usage, event.get("usage"))
                        continue
                    if event_type == "message_stop":
                        for state in _remaining_tools(tools):
                            yield _completed_tool(state)
                        if raw_usage:
                            yield ProviderEvent(
                                type="usage",
                                usage=normalize_anthropic_usage(raw_usage),
                            )
                        yield ProviderEvent(
                            type="completed",
                            stop_reason=_stop_reason(stop_reason, bool(tools)),
                        )
                        return
        except ProviderRequestError:
            raise
        except httpx.HTTPStatusError as exc:
            raise http_status_error("Anthropic", exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise network_error("Anthropic") from exc
        finally:
            if owns_client:
                await client.aclose()

        raise ProviderRequestError(
            "Anthropic stream ended before message_stop.",
            retryable=True,
            stage="stream",
        )


def build_anthropic_payload(request: ProviderRequest) -> dict[str, Any]:
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []
    for message_index, message in enumerate(request.messages):
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
            continue
        if message.role == "tool":
            if not message.tool_call_id:
                raise _validation_error("Anthropic tool result requires tool_call_id.")
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id,
                            "content": message.content or "",
                        }
                    ],
                }
            )
            continue
        if message.role == "assistant":
            content: list[dict[str, Any]] = []
            if message.content:
                content.append({"type": "text", "text": message.content})
            for call_index, call in enumerate(message.tool_calls):
                function = call.get("function")
                if not isinstance(function, Mapping) or not function.get("name"):
                    raise _validation_error(
                        "Anthropic tool call requires a function name."
                    )
                content.append(
                    {
                        "type": "tool_use",
                        "id": str(
                            call.get("id") or f"call_{message_index}_{call_index}"
                        ),
                        "name": str(function["name"]),
                        "input": _json_object(function.get("arguments")),
                    }
                )
            messages.append({"role": "assistant", "content": content or ""})
            continue
        if message.images:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        *(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": image.mime_type,
                                    "data": image.data_base64,
                                },
                            }
                            for image in message.images
                        ),
                        {"type": "text", "text": message.content or ""},
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": message.content or ""})

    payload: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
        "max_tokens": request.max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
        "stream": True,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if request.tools:
        payload["tools"] = [_anthropic_tool(tool) for tool in request.tools]
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    return payload


def normalize_anthropic_usage(raw: Mapping[str, Any]) -> ProviderUsage:
    uncached = _integer(raw.get("input_tokens"))
    cached = _integer(raw.get("cache_read_input_tokens"))
    cache_write = _integer(raw.get("cache_creation_input_tokens"))
    return ProviderUsage(
        input_tokens=uncached + cached + cache_write,
        cached_input_tokens=cached,
        cache_write_tokens=cache_write,
        uncached_input_tokens=uncached,
        output_tokens=_integer(raw.get("output_tokens")),
        raw=dict(raw),
    )


def _anthropic_tool(tool: Mapping[str, Any]) -> dict[str, Any]:
    function = tool.get("function")
    if not isinstance(function, Mapping) or not function.get("name"):
        raise _validation_error("Anthropic tool definition requires a function name.")
    result: dict[str, Any] = {
        "name": str(function["name"]),
        "input_schema": dict(function.get("parameters") or {"type": "object"}),
    }
    if function.get("description"):
        result["description"] = str(function["description"])
    return result


def _event_from_line(line: str) -> Mapping[str, Any] | None:
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if not data:
        return None
    try:
        event = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ProviderRequestError(
            "Anthropic returned an invalid streaming event.",
            retryable=False,
            stage="stream",
        ) from exc
    if not isinstance(event, Mapping):
        raise ProviderRequestError(
            "Anthropic returned an invalid streaming event.",
            retryable=False,
            stage="stream",
        )
    return event


def _tool_state(
    index: int, block: Mapping[str, Any], states: dict[int, _ToolState]
) -> _ToolState:
    state = _ToolState(
        index=index,
        call_id=str(block.get("id") or f"anthropic_call_{index}"),
        name=str(block["name"]) if block.get("name") else None,
    )
    states[index] = state
    return state


def _remaining_tools(states: dict[int, _ToolState]) -> list[_ToolState]:
    result: list[_ToolState] = []
    for index in sorted(states):
        state = states[index]
        if not state.completed:
            state.completed = True
            result.append(state)
    return result


def _completed_tool(state: _ToolState) -> ProviderEvent:
    return ProviderEvent(
        type="tool_call_completed",
        tool_call_id=state.call_id,
        tool_name=state.name,
        arguments_json=state.arguments or "{}",
    )


def _merge_usage(target: dict[str, Any], raw: object) -> None:
    if not isinstance(raw, Mapping):
        return
    for key in (
        "input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "output_tokens",
    ):
        if key in raw:
            target[key] = _integer(raw[key])


def _stream_error(event: Mapping[str, Any]) -> ProviderRequestError:
    error = event.get("error")
    code = (
        str(error.get("type") or "unknown") if isinstance(error, Mapping) else "unknown"
    )
    return ProviderRequestError(
        f"Anthropic stream failed ({code}).",
        retryable=code in {"overloaded_error", "rate_limit_error", "api_error"},
        stage="stream",
    )


def _stop_reason(value: str | None, has_tools: bool) -> str:
    if has_tools or value == "tool_use":
        return "tool_calls"
    if value == "max_tokens":
        return "length"
    if value in {None, "end_turn", "stop_sequence"}:
        return "stop"
    return value or "stop"


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise _validation_error("Anthropic tool arguments must be valid JSON.") from exc
    if not isinstance(parsed, Mapping):
        raise _validation_error("Anthropic tool arguments must be a JSON object.")
    return dict(parsed)


def _json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _validation_error(message: str) -> ProviderRequestError:
    return ProviderRequestError(
        message,
        retryable=False,
        stage="validation",
    )


__all__ = [
    "ANTHROPIC_VERSION",
    "DEFAULT_ANTHROPIC_BASE_URL",
    "AnthropicMessagesAdapter",
    "build_anthropic_payload",
    "normalize_anthropic_usage",
]
