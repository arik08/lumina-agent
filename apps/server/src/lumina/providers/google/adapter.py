from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from lumina.http_client import TrustManager, TrustProfile, create_http_client

from ..constants import DEFAULT_GOOGLE_BASE_URL, GOOGLE_PROVIDER_ID
from ..errors import ProviderConfigurationError, ProviderRequestError
from ..http import http_status_error, network_error, validate_http_base_url
from ..types import (
    ProviderCapabilities,
    ProviderEvent,
    ProviderRequest,
    ProviderUsage,
)
from ..usage import derive_uncached_input_tokens


PROVIDER_ID = GOOGLE_PROVIDER_ID


@dataclass(slots=True)
class _ToolState:
    candidate_index: int
    part_index: int
    call_id: str
    name: str | None
    arguments: str = ""
    completed: bool = False
    thought_signature: str | None = None


class GoogleGeminiAdapter:
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
        base_url: str = DEFAULT_GOOGLE_BASE_URL,
        client: httpx.AsyncClient | None = None,
        trust_profile: TrustProfile | None = None,
    ) -> None:
        secret = api_key.strip()
        if not secret:
            raise ProviderConfigurationError(
                "Google credentials are not configured; GOOGLE_API_KEY is required."
            )
        self.base_url = validate_http_base_url(base_url, "Google Gemini")
        self._api_key = secret
        self._client = client
        self._trust_profile = trust_profile

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        client = self._client
        owns_client = client is None
        if client is None:
            profile = self._trust_profile or TrustManager().initialize()
            client = create_http_client(profile)

        states: dict[tuple[int, int], _ToolState] = {}
        usage: Mapping[str, Any] | None = None
        finish_reason: str | None = None
        try:
            async with client.stream(
                "POST",
                self._stream_url(request.model),
                params={"alt": "sse"},
                headers={
                    "x-goog-api-key": self._api_key,
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                },
                json=build_google_payload(request),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    chunk = _event_from_line(line)
                    if chunk is None:
                        continue
                    if isinstance(chunk.get("error"), Mapping):
                        raise _stream_error(chunk)
                    prompt_feedback = chunk.get("promptFeedback")
                    if isinstance(prompt_feedback, Mapping) and prompt_feedback.get(
                        "blockReason"
                    ):
                        raise ProviderRequestError(
                            f"Google Gemini blocked the prompt ({prompt_feedback['blockReason']}).",
                            retryable=False,
                            stage="safety",
                        )
                    raw_usage = chunk.get("usageMetadata")
                    if isinstance(raw_usage, Mapping):
                        usage = raw_usage
                    candidates = chunk.get("candidates")
                    if not isinstance(candidates, list):
                        continue
                    for fallback_index, candidate in enumerate(candidates):
                        if not isinstance(candidate, Mapping):
                            continue
                        candidate_index = _integer(
                            candidate.get("index"), fallback_index
                        )
                        if candidate.get("finishReason"):
                            finish_reason = str(candidate["finishReason"])
                        content = candidate.get("content")
                        parts = (
                            content.get("parts")
                            if isinstance(content, Mapping)
                            else None
                        )
                        if not isinstance(parts, list):
                            continue
                        for part_index, part in enumerate(parts):
                            if (
                                not isinstance(part, Mapping)
                                or part.get("thought") is True
                            ):
                                continue
                            text = part.get("text")
                            if isinstance(text, str) and text:
                                yield ProviderEvent(type="text_delta", text=text)
                            function_call = part.get("functionCall")
                            if not isinstance(function_call, Mapping):
                                continue
                            key = (candidate_index, part_index)
                            state = states.get(key)
                            if state is None:
                                state = _new_tool_state(
                                    candidate_index, part_index, part, function_call
                                )
                                states[key] = state
                                yield ProviderEvent(
                                    type="tool_call_started",
                                    tool_call_id=state.call_id,
                                    tool_name=state.name,
                                    provider_metadata=_tool_metadata(state),
                                )
                            _update_tool_state(state, part, function_call)
                            arguments = _json_text(function_call.get("args"))
                            if arguments and not state.arguments:
                                state.arguments = arguments
                                yield ProviderEvent(
                                    type="tool_call_delta",
                                    tool_call_id=state.call_id,
                                    tool_name=state.name,
                                    arguments_delta=arguments,
                                    provider_metadata=_tool_metadata(state),
                                )
                            elif arguments:
                                state.arguments = arguments
        except ProviderRequestError:
            raise
        except httpx.HTTPStatusError as exc:
            raise http_status_error("Google Gemini", exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise network_error("Google Gemini") from exc
        finally:
            if owns_client:
                await client.aclose()

        if finish_reason is None:
            raise ProviderRequestError(
                "Google Gemini stream ended before a finish reason.",
                retryable=True,
                stage="stream",
            )
        if finish_reason not in {"STOP", "MAX_TOKENS"}:
            raise ProviderRequestError(
                f"Google Gemini generation failed ({finish_reason}).",
                retryable=False,
                stage="generation",
            )
        for state in _remaining_tools(states):
            yield _completed_tool(state)
        if usage is not None:
            yield ProviderEvent(type="usage", usage=normalize_google_usage(usage))
        yield ProviderEvent(
            type="completed",
            stop_reason=(
                "tool_calls"
                if states
                else "length"
                if finish_reason == "MAX_TOKENS"
                else "stop"
            ),
        )

    def _stream_url(self, model: str) -> str:
        model_id = model.removeprefix("models/").strip()
        if not model_id:
            raise _validation_error("Google Gemini model ID is required.")
        return (
            f"{self.base_url}/models/{quote(model_id, safe='')}:streamGenerateContent"
        )


def build_google_payload(request: ProviderRequest) -> dict[str, Any]:
    system_parts: list[dict[str, str]] = []
    contents: list[dict[str, Any]] = []
    for message_index, message in enumerate(request.messages):
        if message.role == "system":
            if message.content:
                system_parts.append({"text": message.content})
            continue
        if message.role == "tool":
            if not message.name or not message.tool_call_id:
                raise _validation_error(
                    "Google Gemini tool result requires name and tool_call_id."
                )
            response = _tool_result(message.content)
            function_response: dict[str, Any] = {
                "id": message.tool_call_id,
                "name": message.name,
                "response": response,
            }
            contents.append(
                {"role": "user", "parts": [{"functionResponse": function_response}]}
            )
            continue
        if message.role == "assistant":
            parts: list[dict[str, Any]] = []
            if message.content:
                parts.append({"text": message.content})
            for call_index, call in enumerate(message.tool_calls):
                function = call.get("function")
                if not isinstance(function, Mapping) or not function.get("name"):
                    raise _validation_error(
                        "Google Gemini tool call requires a function name."
                    )
                call_id = str(
                    call.get("id") or f"gemini_call_{message_index}_{call_index}"
                )
                function_call: dict[str, Any] = {
                    "id": call_id,
                    "name": str(function["name"]),
                    "args": _json_object(function.get("arguments")),
                }
                metadata = _call_metadata(message.provider_metadata, call_id)
                signature = metadata.get("thought_signature")
                part: dict[str, Any] = {"functionCall": function_call}
                if isinstance(signature, str) and signature:
                    part["thoughtSignature"] = signature
                parts.append(part)
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
            continue
        contents.append(
            {
                "role": "user",
                "parts": [
                    *(
                        {
                            "inlineData": {
                                "mimeType": image.mime_type,
                                "data": image.data_base64,
                            }
                        }
                        for image in message.images
                    ),
                    {"text": message.content or ""},
                ],
            }
        )

    payload: dict[str, Any] = {"contents": contents}
    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}
    if request.tools:
        payload["tools"] = [
            {"functionDeclarations": [_google_tool(tool) for tool in request.tools]}
        ]
    generation_config: dict[str, Any] = {}
    if request.max_output_tokens is not None:
        generation_config["maxOutputTokens"] = request.max_output_tokens
    if request.temperature is not None:
        generation_config["temperature"] = request.temperature
    if request.response_format is not None:
        _apply_response_format(generation_config, request.response_format)
    thinking_config = _google_thinking_config(request.model, request.effort)
    if thinking_config is not None:
        generation_config["thinkingConfig"] = thinking_config
    if generation_config:
        payload["generationConfig"] = generation_config
    return payload


def _google_thinking_config(model: str, effort: str | None) -> dict[str, Any] | None:
    normalized_effort = (effort or "").strip().casefold()
    if normalized_effort in {"", "auto", "none"}:
        return None
    normalized_model = model.removeprefix("models/").strip().casefold()
    if normalized_model.startswith("gemini-3"):
        level = "high" if normalized_effort in {"xhigh", "max"} else normalized_effort
        if level in {"minimal", "low", "medium", "high"}:
            return {"thinkingLevel": level}
        return None
    if normalized_model.startswith("gemini-2.5"):
        budget = {
            "minimal": 0,
            "low": 1_024,
            "medium": 8_192,
            "high": 24_576,
            "xhigh": 24_576,
            "max": 24_576,
        }.get(normalized_effort)
        return {"thinkingBudget": budget} if budget is not None else None
    return None


def normalize_google_usage(raw: Mapping[str, Any]) -> ProviderUsage:
    input_tokens = _integer(raw.get("promptTokenCount"))
    cached = _integer(raw.get("cachedContentTokenCount"))
    raw_reasoning_tokens = raw.get("thoughtsTokenCount")
    reasoning_tokens = (
        _integer(raw_reasoning_tokens) if raw_reasoning_tokens is not None else None
    )
    output_tokens = _integer(raw.get("candidatesTokenCount")) + (reasoning_tokens or 0)
    return ProviderUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        uncached_input_tokens=derive_uncached_input_tokens(input_tokens, cached),
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        raw=dict(raw),
    )


def _google_tool(tool: Mapping[str, Any]) -> dict[str, Any]:
    function = tool.get("function")
    if not isinstance(function, Mapping) or not function.get("name"):
        raise _validation_error(
            "Google Gemini tool definition requires a function name."
        )
    result: dict[str, Any] = {
        "name": str(function["name"]),
        "parametersJsonSchema": dict(function.get("parameters") or {"type": "object"}),
    }
    if function.get("description"):
        result["description"] = str(function["description"])
    return result


def _apply_response_format(
    generation_config: dict[str, Any], response_format: Mapping[str, Any]
) -> None:
    format_type = response_format.get("type")
    if format_type not in {"json_object", "json_schema"}:
        return
    generation_config["responseMimeType"] = "application/json"
    schema_container = response_format.get("json_schema")
    if isinstance(schema_container, Mapping):
        schema = schema_container.get("schema")
        if isinstance(schema, Mapping):
            generation_config["responseJsonSchema"] = dict(schema)


def _event_from_line(line: str) -> Mapping[str, Any] | None:
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if not data:
        return None
    try:
        chunk = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ProviderRequestError(
            "Google Gemini returned an invalid streaming event.",
            retryable=False,
            stage="stream",
        ) from exc
    if not isinstance(chunk, Mapping):
        raise ProviderRequestError(
            "Google Gemini returned an invalid streaming event.",
            retryable=False,
            stage="stream",
        )
    return chunk


def _new_tool_state(
    candidate_index: int,
    part_index: int,
    part: Mapping[str, Any],
    function_call: Mapping[str, Any],
) -> _ToolState:
    signature = part.get("thoughtSignature")
    return _ToolState(
        candidate_index=candidate_index,
        part_index=part_index,
        call_id=str(
            function_call.get("id") or f"gemini_call_{candidate_index}_{part_index}"
        ),
        name=(str(function_call["name"]) if function_call.get("name") else None),
        thought_signature=(
            str(signature) if isinstance(signature, str) and signature else None
        ),
    )


def _update_tool_state(
    state: _ToolState,
    part: Mapping[str, Any],
    function_call: Mapping[str, Any],
) -> None:
    if function_call.get("id"):
        state.call_id = str(function_call["id"])
    if function_call.get("name"):
        state.name = str(function_call["name"])
    signature = part.get("thoughtSignature")
    if isinstance(signature, str) and signature:
        state.thought_signature = signature


def _remaining_tools(
    states: dict[tuple[int, int], _ToolState],
) -> list[_ToolState]:
    result: list[_ToolState] = []
    for key in sorted(states):
        state = states[key]
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
        provider_metadata=_tool_metadata(state),
    )


def _tool_metadata(state: _ToolState) -> dict[str, str]:
    if state.thought_signature:
        return {"thought_signature": state.thought_signature}
    return {}


def _call_metadata(metadata: Mapping[str, Any], call_id: str) -> Mapping[str, Any]:
    value = metadata.get(call_id)
    return value if isinstance(value, Mapping) else {}


def _tool_result(content: str | None) -> dict[str, Any]:
    if not content:
        return {"result": ""}
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {"result": content}
    if isinstance(parsed, Mapping):
        return dict(parsed)
    return {"result": parsed}


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise _validation_error(
            "Google Gemini tool arguments must be valid JSON."
        ) from exc
    if not isinstance(parsed, Mapping):
        raise _validation_error("Google Gemini tool arguments must be a JSON object.")
    return dict(parsed)


def _json_text(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _stream_error(chunk: Mapping[str, Any]) -> ProviderRequestError:
    error = chunk.get("error")
    code = (
        str(error.get("status") or error.get("code") or "unknown")
        if isinstance(error, Mapping)
        else "unknown"
    )
    return ProviderRequestError(
        f"Google Gemini stream failed ({code}).",
        retryable=code in {"429", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL"},
        stage="stream",
    )


def _integer(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default


def _validation_error(message: str) -> ProviderRequestError:
    return ProviderRequestError(
        message,
        retryable=False,
        stage="validation",
    )


__all__ = [
    "DEFAULT_GOOGLE_BASE_URL",
    "GoogleGeminiAdapter",
    "build_google_payload",
    "normalize_google_usage",
]
