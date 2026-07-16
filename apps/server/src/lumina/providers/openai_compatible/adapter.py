from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from lumina.http_client import (
    HttpClientOptions,
    TrustManager,
    TrustProfile,
    create_http_client,
)

from ..errors import ProviderConfigurationError, ProviderRequestError
from ..http import validate_http_base_url
from ..types import (
    ProviderCapabilities,
    ProviderEvent,
    ProviderMessage,
    ProviderRequest,
    ProviderUsage,
)


logger = logging.getLogger(__name__)


def _message_payload(message: ProviderMessage) -> dict[str, Any]:
    result: dict[str, Any] = {"role": message.role}
    if message.images:
        result["content"] = [
            {"type": "text", "text": message.content or ""},
            *(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image.mime_type};base64,{image.data_base64}"
                    },
                }
                for image in message.images
            ),
        ]
    elif message.content is not None:
        result["content"] = message.content
    if message.tool_call_id is not None:
        result["tool_call_id"] = message.tool_call_id
    if message.name is not None:
        result["name"] = message.name
    if message.tool_calls:
        result["tool_calls"] = [dict(call) for call in message.tool_calls]
    return result


def build_chat_completions_payload(request: ProviderRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [_message_payload(message) for message in request.messages],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if request.tools:
        payload["tools"] = [dict(tool) for tool in request.tools]
    if request.effort is not None:
        payload["reasoning_effort"] = request.effort
    if request.response_format is not None:
        payload["response_format"] = dict(request.response_format)
    if request.max_output_tokens is not None:
        payload["max_completion_tokens"] = request.max_output_tokens
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    return payload


def normalize_openai_usage(raw: Mapping[str, Any]) -> ProviderUsage:
    input_tokens = int(raw.get("prompt_tokens") or raw.get("input_tokens") or 0)
    output_tokens = int(raw.get("completion_tokens") or raw.get("output_tokens") or 0)
    prompt_details = (
        raw.get("prompt_tokens_details") or raw.get("input_tokens_details") or {}
    )
    if not isinstance(prompt_details, Mapping):
        prompt_details = {}
    cached = int(prompt_details.get("cached_tokens") or 0)
    cache_write = int(
        prompt_details.get("cache_write_tokens")
        or prompt_details.get("cache_creation_input_tokens")
        or 0
    )
    return ProviderUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        cache_write_tokens=cache_write,
        uncached_input_tokens=max(0, input_tokens - cached),
        output_tokens=output_tokens,
        raw=dict(raw),
    )


@dataclass(slots=True)
class _ToolState:
    call_id: str
    name: str | None = None
    arguments: str = ""


class _OptionalPayloadFallback(RuntimeError):
    """Retry once the rejected optional fields have been removed."""


class OpenAICompatibleAdapter:
    capabilities = ProviderCapabilities(
        tools=True,
        structured_output=True,
        reasoning_effort=True,
    )

    def __init__(
        self,
        *,
        provider_id: str,
        base_url: str,
        headers: Mapping[str, str] | None = None,
        require_authorization: bool = True,
        client: httpx.AsyncClient | None = None,
        trust_profile: TrustProfile | None = None,
        http_options: HttpClientOptions | None = None,
        payload_builder: Callable[[ProviderRequest], dict[str, Any]] | None = None,
        optional_payload_fields: tuple[str, ...] = (),
    ) -> None:
        self.provider_id = provider_id
        self.base_url = _validated_base_url(base_url)
        self._headers = dict(headers or {})
        self._client = client
        self._trust_profile = trust_profile
        self._http_options = http_options
        self._payload_builder = payload_builder or build_chat_completions_payload
        self._optional_payload_fields = frozenset(optional_payload_fields)
        self._disabled_optional_payload_fields: set[str] = set()
        if require_authorization and not any(
            key.casefold() == "authorization" and value.strip()
            for key, value in self._headers.items()
        ):
            raise ProviderConfigurationError(
                f"{provider_id} credentials are not configured; an Authorization header is required."
            )

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        client = self._client
        owns_client = client is None
        if client is None:
            profile = self._trust_profile or TrustManager().initialize()
            client = create_http_client(profile, options=self._http_options)

        tool_states: dict[int, _ToolState] = {}
        stop_reason: str | None = None
        terminal_received = False
        try:
            payload = self._request_payload(request)
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers,
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    if self._disable_rejected_optional_fields(body, payload):
                        raise _OptionalPayloadFallback
                response.raise_for_status()
                async for data in _iter_sse_payloads(response):
                    if not data:
                        continue
                    if data == "[DONE]":
                        terminal_received = True
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ProviderRequestError(
                            f"{self.provider_id} returned an invalid streaming event.",
                            retryable=True,
                            stage="stream",
                        ) from exc
                    if not isinstance(chunk, Mapping):
                        raise ProviderRequestError(
                            f"{self.provider_id} returned an invalid streaming event.",
                            retryable=True,
                            stage="stream",
                        )

                    if isinstance(chunk.get("error"), Mapping):
                        error_payload = chunk["error"]
                        stage = (
                            "context"
                            if _is_context_overflow_payload(error_payload)
                            else "stream"
                        )
                        status_code = _integer(
                            error_payload.get("status")
                            or error_payload.get("status_code")
                        )
                        raise ProviderRequestError(
                            f"{self.provider_id} returned a streaming error.",
                            retryable=_is_retryable_stream_error(error_payload),
                            stage=stage,
                            status_code=status_code or None,
                            retry_after_seconds=_retry_after_seconds(error_payload),
                            context_window_tokens=(
                                _context_window_tokens(error_payload)
                                if stage == "context"
                                else None
                            ),
                        )

                    usage = chunk.get("usage")
                    if isinstance(usage, Mapping):
                        yield ProviderEvent(
                            type="usage", usage=normalize_openai_usage(usage)
                        )

                    choices = chunk.get("choices") or ()
                    for choice in choices:
                        if not isinstance(choice, Mapping):
                            continue
                        delta = choice.get("delta") or {}
                        if not isinstance(delta, Mapping):
                            delta = {}
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            yield ProviderEvent(type="text_delta", text=content)

                        for call in delta.get("tool_calls") or ():
                            if not isinstance(call, Mapping):
                                continue
                            index = _integer(call.get("index"))
                            function = call.get("function") or {}
                            if not isinstance(function, Mapping):
                                function = {}
                            state = tool_states.get(index)
                            if state is None:
                                state = _ToolState(
                                    call_id=str(call.get("id") or f"call_{index}"),
                                    name=str(function.get("name"))
                                    if function.get("name")
                                    else None,
                                )
                                tool_states[index] = state
                                yield ProviderEvent(
                                    type="tool_call_started",
                                    tool_call_id=state.call_id,
                                    tool_name=state.name,
                                )
                            elif function.get("name"):
                                state.name = str(function["name"])

                            argument_delta = function.get("arguments")
                            if isinstance(argument_delta, str) and argument_delta:
                                state.arguments += argument_delta
                                yield ProviderEvent(
                                    type="tool_call_delta",
                                    tool_call_id=state.call_id,
                                    tool_name=state.name,
                                    arguments_delta=argument_delta,
                                )

                        if choice.get("finish_reason") is not None:
                            stop_reason = str(choice["finish_reason"])
                            terminal_received = True
        except _OptionalPayloadFallback:
            async for event in self.stream(request):
                yield event
            return
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            stage = (
                "context"
                if status in {400, 413, 422}
                and _is_context_overflow_response(exc.response)
                else _stage_for_status(status)
            )
            raise ProviderRequestError(
                f"{self.provider_id} request failed during {stage} (HTTP {status}).",
                retryable=status in {408, 409, 425, 429} or status >= 500,
                stage=stage,
                status_code=status,
                retry_after_seconds=_retry_after_seconds(
                    exc.response.headers.get("Retry-After")
                ),
                context_window_tokens=(
                    _context_window_from_response(exc.response)
                    if stage == "context"
                    else None
                ),
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderRequestError(
                f"{self.provider_id} network request failed.",
                retryable=True,
                stage="network",
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        if not terminal_received:
            raise ProviderRequestError(
                f"{self.provider_id} stream ended before a terminal event.",
                retryable=True,
                stage="stream",
            )
        for index in sorted(tool_states):
            state = tool_states[index]
            yield ProviderEvent(
                type="tool_call_completed",
                tool_call_id=state.call_id,
                tool_name=state.name,
                arguments_json=state.arguments,
            )
        yield ProviderEvent(type="completed", stop_reason=stop_reason or "stop")

    def _request_payload(self, request: ProviderRequest) -> dict[str, Any]:
        payload = self._payload_builder(request)
        for field in self._disabled_optional_payload_fields:
            payload.pop(field, None)
        if "prompt_cache_key" in self._disabled_optional_payload_fields:
            payload.pop("prompt_cache_retention", None)
        return payload

    def _disable_rejected_optional_fields(
        self, body: bytes, sent_payload: Mapping[str, Any]
    ) -> bool:
        rejected = _unsupported_optional_fields(body, self._optional_payload_fields)
        sent_rejected = rejected.intersection(sent_payload)
        if not sent_rejected:
            return False
        new_fields = rejected - self._disabled_optional_payload_fields
        if new_fields:
            self._disabled_optional_payload_fields.update(new_fields)
            if "prompt_cache_key" in new_fields:
                self._disabled_optional_payload_fields.add("prompt_cache_retention")
            logger.warning(
                "%s rejected optional request fields; retrying without %s",
                self.provider_id,
                ", ".join(sorted(self._disabled_optional_payload_fields)),
            )
        # Another concurrent Run may already have disabled the same field after
        # this request was built. This request still needs its own clean retry.
        return True

    async def discover_models(self) -> tuple[str, ...]:
        """Return remote candidates only; activation remains an admin DB action."""
        client = self._client
        owns_client = client is None
        if client is None:
            profile = self._trust_profile or TrustManager().initialize()
            client = create_http_client(profile)
        try:
            response = await client.get(
                f"{self.base_url}/models",
                headers=self._headers,
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise ProviderRequestError(
                    f"{self.provider_id} model discovery returned invalid JSON.",
                    retryable=False,
                    stage="discovery",
                ) from exc
            if not isinstance(payload, Mapping) or not isinstance(
                payload.get("data"), list
            ):
                raise ProviderRequestError(
                    f"{self.provider_id} model discovery returned an invalid payload.",
                    retryable=False,
                    stage="discovery",
                )
            model_ids: list[str] = []
            for item in payload["data"][:1_000]:
                if not isinstance(item, Mapping):
                    continue
                model_id = item.get("id")
                if isinstance(model_id, str) and model_id.strip():
                    model_ids.append(model_id.strip())
            return tuple(dict.fromkeys(model_ids))
        except ProviderRequestError:
            raise
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            stage = _stage_for_status(status)
            raise ProviderRequestError(
                f"{self.provider_id} model discovery failed during {stage} "
                f"(HTTP {status}).",
                retryable=status in {408, 409, 425, 429} or status >= 500,
                stage=stage,
                status_code=status,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderRequestError(
                f"{self.provider_id} model discovery network request failed.",
                retryable=True,
                stage="network",
            ) from exc
        finally:
            if owns_client:
                await client.aclose()


def _is_context_overflow_response(response: httpx.Response) -> bool:
    """Classify only known context errors without exposing the response body."""
    try:
        payload = response.json()
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (json.JSONDecodeError, ValueError):
        text = response.text
    return _is_context_overflow_payload(text)


def _is_context_overflow_payload(value: object) -> bool:
    normalized = (
        value.lower()
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, default=str).lower()
    )
    return any(
        marker in normalized
        for marker in (
            "prompt too long",
            "context_length_exceeded",
            "input exceeds",
            "context length",
            "maximum context",
            "context window",
            "too many tokens",
            "too large for the model",
        )
    )


_CONTEXT_WINDOW_FIELD_NAMES = frozenset(
    {
        "contextlength",
        "contextwindow",
        "maxcontextlength",
        "maxcontextwindow",
        "maximumcontextlength",
        "maximumcontextwindow",
    }
)
_CONTEXT_WINDOW_PATTERNS = (
    re.compile(
        r"(?:maximum|max|actual)\s+context(?:\s+window|\s+length)?\s*"
        r"(?:is|of|:|=)\s*([0-9][0-9_,]*)\s*tokens?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"context(?:\s+window|\s+length)\s*(?:is|of|:|=)\s*"
        r"([0-9][0-9_,]*)\s*tokens?\b",
        re.IGNORECASE,
    ),
)


def _retry_after_seconds(value: object) -> float | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z]", "", str(key).casefold())
            if normalized_key in {"retryafter", "retryafterseconds"}:
                parsed = _retry_after_seconds(item)
                if parsed is not None:
                    return parsed
        for item in value.values():
            if isinstance(item, (Mapping, list, tuple)):
                parsed = _retry_after_seconds(item)
                if parsed is not None:
                    return parsed
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, (Mapping, list, tuple)):
                parsed = _retry_after_seconds(item)
                if parsed is not None:
                    return parsed
        return None
    if isinstance(value, bool):
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not 0 <= parsed < float("inf"):
        return None
    return min(parsed, 600.0)


def _context_window_from_response(response: httpx.Response) -> int | None:
    try:
        payload: object = response.json()
    except (json.JSONDecodeError, ValueError):
        payload = response.text
    return _context_window_tokens(payload)


def _context_window_tokens(value: object) -> int | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z]", "", str(key).casefold())
            if normalized_key in _CONTEXT_WINDOW_FIELD_NAMES:
                parsed = _context_token_count(item)
                if parsed is not None:
                    return parsed
        for item in value.values():
            parsed = _context_window_tokens(item)
            if parsed is not None:
                return parsed
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            parsed = _context_window_tokens(item)
            if parsed is not None:
                return parsed
        return None
    if not isinstance(value, str):
        return None
    for pattern in _CONTEXT_WINDOW_PATTERNS:
        match = pattern.search(value)
        if match is not None:
            parsed = _context_token_count(match.group(1))
            if parsed is not None:
                return parsed
    return None


def _context_token_count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    normalized = str(value).replace(",", "").replace("_", "").strip()
    if not normalized.isdigit():
        return None
    parsed = int(normalized)
    return parsed if 1_024 <= parsed <= 10_000_000 else None


async def _iter_sse_payloads(response: httpx.Response) -> AsyncIterator[str]:
    """Yield complete SSE data payloads, including multi-line gateway events."""

    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield "\n".join(data_lines).strip()
                data_lines.clear()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
            continue
        stripped = line.strip()
        if not data_lines and stripped.startswith("{") and stripped.endswith("}"):
            yield stripped
    if data_lines:
        yield "\n".join(data_lines).strip()


def _unsupported_optional_fields(body: bytes, candidates: frozenset[str]) -> set[str]:
    if not body or not candidates:
        return set()
    text = body.decode("utf-8", errors="replace").casefold()
    if not any(
        marker in text
        for marker in (
            "unsupported",
            "invalid parameter",
            "unknown parameter",
            "unrecognized",
            "unexpected",
            "not permitted",
            "extra inputs",
        )
    ):
        return set()
    return {
        field
        for field in candidates
        if field.casefold() in text or field.replace("_", "-").casefold() in text
    }


def _is_retryable_stream_error(error: Mapping[str, Any]) -> bool:
    status = error.get("status") or error.get("status_code")
    if isinstance(status, int) and (status in {408, 409, 425, 429} or status >= 500):
        return True
    normalized = json.dumps(error, ensure_ascii=False, default=str).casefold()
    return any(
        marker in normalized
        for marker in (
            "rate_limit",
            "rate limit",
            "overload",
            "server_error",
            "service_unavailable",
            "temporarily unavailable",
            "timeout",
            "timed out",
        )
    )


def _validated_base_url(value: str) -> str:
    return validate_http_base_url(value, "Provider")


def _stage_for_status(status: int) -> str:
    if status in {401, 403}:
        return "authentication"
    if status == 404:
        return "endpoint"
    if status == 429:
        return "rate_limit"
    return "request"


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0
