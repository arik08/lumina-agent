from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from lumina.http_client import TrustManager, TrustProfile, create_http_client

from ..constants import DEFAULT_OPENAI_BASE_URL, OPENAI_PROVIDER_ID
from ..errors import ProviderConfigurationError, ProviderRequestError
from ..http import validate_http_base_url
from ..openai_compatible import normalize_openai_usage
from ..types import (
    ProviderCapabilities,
    ProviderEvent,
    ProviderMessage,
    ProviderRequest,
    RESPONSES_STATE_METADATA_KEY,
)


PROVIDER_ID = OPENAI_PROVIDER_ID
_RETRYABLE_ERROR_CODES = {
    "rate_limit_exceeded",
    "server_error",
    "temporarily_unavailable",
    "timeout",
}


def _responses_state_items(message: ProviderMessage) -> list[dict[str, Any]]:
    raw_items = message.provider_metadata.get(RESPONSES_STATE_METADATA_KEY)
    if not isinstance(raw_items, (list, tuple)):
        return []
    return [
        dict(item)
        for item in raw_items
        if isinstance(item, Mapping) and item.get("type") in {"reasoning", "compaction"}
    ]


def _message_items(message: ProviderMessage) -> list[dict[str, Any]]:
    if message.role == "tool":
        if not message.tool_call_id:
            raise ProviderConfigurationError(
                "OpenAI function call output requires a tool_call_id."
            )
        return [
            {
                "type": "function_call_output",
                "call_id": message.tool_call_id,
                "output": message.content or "",
            }
        ]

    items: list[dict[str, Any]] = []
    if message.content is not None or message.images:
        content: str | list[dict[str, Any]] = message.content or ""
        if message.images:
            content = [
                {"type": "input_text", "text": message.content or ""},
                *(
                    {
                        "type": "input_image",
                        "image_url": f"data:{image.mime_type};base64,{image.data_base64}",
                    }
                    for image in message.images
                ),
            ]
        items.append({"role": message.role, "content": content})
    for raw_call in message.tool_calls:
        function = raw_call.get("function")
        if not isinstance(function, Mapping):
            continue
        call_id = raw_call.get("id")
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(call_id, str) or not isinstance(name, str):
            continue
        items.append(
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": arguments if isinstance(arguments, str) else "{}",
            }
        )
    return items


def _responses_input_items(
    messages: tuple[ProviderMessage, ...], *, include_state: bool
) -> list[dict[str, Any]]:
    input_items: list[dict[str, Any]] = []
    retained_system_items: list[dict[str, Any]] = []
    for message in messages:
        message_items = _message_items(message)
        if message.role == "system":
            retained_system_items.extend(dict(item) for item in message_items)
        for state_item in _responses_state_items(message) if include_state else ():
            if state_item.get("type") == "compaction":
                input_items = [*retained_system_items, state_item]
            else:
                input_items.append(state_item)
        input_items.extend(message_items)
    return input_items


def _responses_tool(raw_tool: Mapping[str, Any]) -> dict[str, Any]:
    if raw_tool.get("type") != "function":
        return dict(raw_tool)
    function = raw_tool.get("function")
    if not isinstance(function, Mapping):
        return dict(raw_tool)
    result: dict[str, Any] = {"type": "function"}
    for key in ("name", "description", "parameters", "strict"):
        if key in function:
            result[key] = function[key]
    return result


def _responses_text_format(raw_format: Mapping[str, Any]) -> dict[str, Any]:
    format_type = raw_format.get("type")
    if format_type == "json_schema":
        schema = raw_format.get("json_schema")
        if isinstance(schema, Mapping):
            return {"format": {"type": "json_schema", **dict(schema)}}
    return {"format": dict(raw_format)}


def _mark_stable_system_cache_breakpoint(
    *,
    messages: tuple[ProviderMessage, ...],
    input_items: list[dict[str, Any]],
) -> bool:
    stable_system = next(
        (message for message in messages if message.role == "system"),
        None,
    )
    if stable_system is None or not stable_system.content:
        return False

    for item in input_items:
        if item.get("role") != "system":
            continue
        content = item.get("content")
        if isinstance(content, str):
            item["content"] = [
                {
                    "type": "input_text",
                    "text": content,
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }
            ]
            return True
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "input_text" and block.get("text"):
                    block["prompt_cache_breakpoint"] = {"mode": "explicit"}
                    return True
        return False
    return False


def build_responses_payload(request: ProviderRequest) -> dict[str, Any]:
    is_gpt_5_6 = request.model.casefold().startswith("gpt-5.6")
    input_items = _responses_input_items(request.messages, include_state=is_gpt_5_6)
    payload: dict[str, Any] = {
        "model": request.model,
        "input": input_items,
        "stream": True,
        "store": False,
    }
    if request.tools:
        payload["tools"] = [_responses_tool(tool) for tool in request.tools]
    if request.effort is not None:
        payload["reasoning"] = {"effort": request.effort}
    if is_gpt_5_6:
        payload.setdefault("reasoning", {})["context"] = "all_turns"
        payload["include"] = ["reasoning.encrypted_content"]
        compact_threshold = request.metadata.get("compact_threshold_tokens")
        if (
            isinstance(compact_threshold, int)
            and not isinstance(compact_threshold, bool)
            and compact_threshold > 0
        ):
            payload["context_management"] = [
                {"type": "compaction", "compact_threshold": compact_threshold}
            ]
    if request.response_format is not None:
        payload["text"] = _responses_text_format(request.response_format)
    if request.max_output_tokens is not None:
        payload["max_output_tokens"] = request.max_output_tokens
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    prompt_cache_key = request.metadata.get("prompt_cache_key")
    if isinstance(prompt_cache_key, str) and prompt_cache_key:
        payload["prompt_cache_key"] = prompt_cache_key
        if request.model.casefold().startswith("gpt-5.6"):
            options = {"ttl": "30m"}
            if _mark_stable_system_cache_breakpoint(
                messages=request.messages,
                input_items=input_items,
            ):
                options["mode"] = "explicit"
            payload["prompt_cache_options"] = options
        else:
            retention = request.metadata.get("prompt_cache_retention")
            if retention in {"in_memory", "24h"}:
                payload["prompt_cache_retention"] = retention
    return payload


@dataclass(slots=True)
class _ToolState:
    output_index: int
    item_id: str
    call_id: str
    name: str | None
    arguments: str = ""
    started: bool = False
    completed: bool = False


class OpenAIResponsesAdapter:
    provider_id = PROVIDER_ID
    capabilities = ProviderCapabilities(
        tools=True,
        structured_output=True,
        reasoning_effort=True,
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_OPENAI_BASE_URL,
        client: httpx.AsyncClient | None = None,
        trust_profile: TrustProfile | None = None,
        additional_headers: Mapping[str, str] | None = None,
        payload_transform: (
            Callable[[ProviderRequest, dict[str, Any]], dict[str, Any]] | None
        ) = None,
        service_name: str = "OpenAI Responses",
    ) -> None:
        secret = api_key.strip()
        if not secret:
            raise ProviderConfigurationError(
                "OpenAI credentials are not configured; OPENAI_API_KEY is required."
            )
        self.base_url = _validated_base_url(base_url)
        self._authorization = f"Bearer {secret}"
        self._client = client
        self._trust_profile = trust_profile
        self._additional_headers = dict(additional_headers or {})
        self._payload_transform = payload_transform
        self._service_name = service_name

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        client = self._client
        owns_client = client is None
        if client is None:
            profile = self._trust_profile or TrustManager().initialize()
            client = create_http_client(profile)

        states_by_item: dict[str, _ToolState] = {}
        states_by_index: dict[int, _ToolState] = {}
        try:
            payload = build_responses_payload(request)
            if self._payload_transform is not None:
                payload = self._payload_transform(request, payload)
            headers = {
                "Authorization": self._authorization,
                "Accept": "text/event-stream",
            }
            headers.update(self._additional_headers)
            async with client.stream(
                "POST",
                f"{self.base_url}/responses",
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    event = _event_from_line(line)
                    if event is None:
                        continue
                    event_type = event.get("type")
                    if event_type == "response.output_text.delta":
                        delta = event.get("delta")
                        if isinstance(delta, str) and delta:
                            yield ProviderEvent(type="text_delta", text=delta)
                        continue

                    if event_type == "response.output_item.added":
                        item = event.get("item")
                        if (
                            isinstance(item, Mapping)
                            and item.get("type") == "function_call"
                        ):
                            state = _tool_state(
                                event,
                                item=item,
                                states_by_item=states_by_item,
                                states_by_index=states_by_index,
                            )
                            if not state.started:
                                state.started = True
                                yield _tool_started(state)
                        continue

                    if event_type == "response.function_call_arguments.delta":
                        state = _tool_state(
                            event,
                            states_by_item=states_by_item,
                            states_by_index=states_by_index,
                        )
                        if not state.started:
                            state.started = True
                            yield _tool_started(state)
                        delta = event.get("delta")
                        if isinstance(delta, str) and delta:
                            state.arguments += delta
                            yield ProviderEvent(
                                type="tool_call_delta",
                                tool_call_id=state.call_id,
                                tool_name=state.name,
                                arguments_delta=delta,
                            )
                        continue

                    if event_type == "response.function_call_arguments.done":
                        item = event.get("item")
                        state = _tool_state(
                            event,
                            item=item if isinstance(item, Mapping) else None,
                            states_by_item=states_by_item,
                            states_by_index=states_by_index,
                        )
                        if not state.started:
                            state.started = True
                            yield _tool_started(state)
                        _update_final_tool_state(state, event, item)
                        if not state.completed:
                            state.completed = True
                            yield _tool_completed(state)
                        continue

                    if event_type == "response.output_item.done":
                        item = event.get("item")
                        if (
                            isinstance(item, Mapping)
                            and item.get("type") in {"reasoning", "compaction"}
                        ):
                            yield ProviderEvent(
                                type="response_state",
                                provider_metadata={"item": dict(item)},
                            )
                            continue
                        if (
                            isinstance(item, Mapping)
                            and item.get("type") == "function_call"
                        ):
                            state = _tool_state(
                                event,
                                item=item,
                                states_by_item=states_by_item,
                                states_by_index=states_by_index,
                            )
                            if not state.started:
                                state.started = True
                                yield _tool_started(state)
                            _update_final_tool_state(state, event, item)
                            if not state.completed:
                                state.completed = True
                                yield _tool_completed(state)
                        continue

                    if event_type in {"error", "response.error", "response.failed"}:
                        raise _stream_error(event)

                    if event_type in {"response.completed", "response.incomplete"}:
                        response_payload = event.get("response")
                        if not isinstance(response_payload, Mapping):
                            response_payload = {}
                        for provider_event in _final_tool_events(
                            response_payload,
                            states_by_item=states_by_item,
                            states_by_index=states_by_index,
                        ):
                            yield provider_event
                        usage = response_payload.get("usage")
                        if isinstance(usage, Mapping):
                            yield ProviderEvent(
                                type="usage", usage=normalize_openai_usage(usage)
                            )
                        stop_reason = _stop_reason(
                            event_type,
                            response_payload,
                            has_tool_calls=bool(states_by_item),
                        )
                        yield ProviderEvent(type="completed", stop_reason=stop_reason)
                        return
        except ProviderRequestError:
            raise
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            stage = _stage_for_status(status)
            raise ProviderRequestError(
                f"{self._service_name} request failed during {stage} (HTTP {status}).",
                retryable=status in {408, 409, 425, 429} or status >= 500,
                stage=stage,
                status_code=status,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderRequestError(
                f"{self._service_name} network request failed.",
                retryable=True,
                stage="network",
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        raise ProviderRequestError(
            f"{self._service_name} stream ended before a terminal event.",
            retryable=True,
            stage="stream",
        )


def _event_from_line(line: str) -> Mapping[str, Any] | None:
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return None
    try:
        event = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ProviderRequestError(
            "OpenAI Responses returned an invalid streaming event.",
            retryable=False,
            stage="stream",
        ) from exc
    if not isinstance(event, Mapping):
        raise ProviderRequestError(
            "OpenAI Responses returned an invalid streaming event.",
            retryable=False,
            stage="stream",
        )
    return event


def _tool_state(
    event: Mapping[str, Any],
    *,
    states_by_item: dict[str, _ToolState],
    states_by_index: dict[int, _ToolState],
    item: Mapping[str, Any] | None = None,
) -> _ToolState:
    output_index = _integer(event.get("output_index"))
    raw_item_id = event.get("item_id") or (item or {}).get("id")
    item_id = str(raw_item_id or f"output_{output_index}")
    state = states_by_item.get(item_id) or states_by_index.get(output_index)
    if state is None:
        raw_call_id = (item or {}).get("call_id") or event.get("call_id") or item_id
        raw_name = (item or {}).get("name") or event.get("name")
        state = _ToolState(
            output_index=output_index,
            item_id=item_id,
            call_id=str(raw_call_id),
            name=str(raw_name) if raw_name else None,
        )
    elif not state.started:
        raw_call_id = (item or {}).get("call_id") or event.get("call_id")
        raw_name = (item or {}).get("name") or event.get("name")
        if raw_call_id:
            state.call_id = str(raw_call_id)
        if raw_name:
            state.name = str(raw_name)
    initial_arguments = (item or {}).get("arguments")
    if isinstance(initial_arguments, str) and initial_arguments and not state.arguments:
        state.arguments = initial_arguments
    states_by_item[item_id] = state
    states_by_index[output_index] = state
    return state


def _update_final_tool_state(
    state: _ToolState,
    event: Mapping[str, Any],
    item: object,
) -> None:
    item_mapping = item if isinstance(item, Mapping) else {}
    raw_name = item_mapping.get("name") or event.get("name")
    if raw_name:
        state.name = str(raw_name)
    arguments = item_mapping.get("arguments") or event.get("arguments")
    if isinstance(arguments, str):
        state.arguments = arguments


def _final_tool_events(
    response: Mapping[str, Any],
    *,
    states_by_item: dict[str, _ToolState],
    states_by_index: dict[int, _ToolState],
) -> list[ProviderEvent]:
    events: list[ProviderEvent] = []
    output = response.get("output")
    if isinstance(output, list):
        for output_index, raw_item in enumerate(output):
            if (
                not isinstance(raw_item, Mapping)
                or raw_item.get("type") != "function_call"
            ):
                continue
            state = _tool_state(
                {"output_index": output_index},
                item=raw_item,
                states_by_item=states_by_item,
                states_by_index=states_by_index,
            )
            if not state.started:
                state.started = True
                events.append(_tool_started(state))
            _update_final_tool_state(state, {}, raw_item)
            if not state.completed:
                state.completed = True
                events.append(_tool_completed(state))
    for state in sorted(states_by_index.values(), key=lambda value: value.output_index):
        if not state.completed:
            state.completed = True
            events.append(_tool_completed(state))
    return events


def _tool_started(state: _ToolState) -> ProviderEvent:
    return ProviderEvent(
        type="tool_call_started",
        tool_call_id=state.call_id,
        tool_name=state.name,
    )


def _tool_completed(state: _ToolState) -> ProviderEvent:
    return ProviderEvent(
        type="tool_call_completed",
        tool_call_id=state.call_id,
        tool_name=state.name,
        arguments_json=state.arguments,
    )


def _stream_error(event: Mapping[str, Any]) -> ProviderRequestError:
    response = event.get("response")
    nested_error = response.get("error") if isinstance(response, Mapping) else None
    error = nested_error if isinstance(nested_error, Mapping) else event
    raw_code = error.get("code")
    code = str(raw_code) if raw_code else "unknown"
    return ProviderRequestError(
        f"OpenAI Responses stream failed ({code}).",
        retryable=code in _RETRYABLE_ERROR_CODES,
        stage="stream",
    )


def _stop_reason(
    event_type: object,
    response: Mapping[str, Any],
    *,
    has_tool_calls: bool,
) -> str:
    if has_tool_calls:
        return "tool_calls"
    if event_type != "response.incomplete":
        return "stop"
    details = response.get("incomplete_details")
    reason = details.get("reason") if isinstance(details, Mapping) else None
    return "length" if reason == "max_output_tokens" else str(reason or "incomplete")


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _validated_base_url(value: str) -> str:
    return validate_http_base_url(value, "OpenAI")


def _stage_for_status(status: int) -> str:
    if status in {401, 403}:
        return "authentication"
    if status == 404:
        return "endpoint"
    if status == 429:
        return "rate_limit"
    return "request"


__all__ = [
    "DEFAULT_OPENAI_BASE_URL",
    "OpenAIResponsesAdapter",
    "build_responses_payload",
]
