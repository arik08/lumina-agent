from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from lumina.http_client import TrustManager, TrustProfile, create_http_client

from ..errors import ProviderConfigurationError, ProviderRequestError
from ..types import (
    ProviderCapabilities,
    ProviderEvent,
    ProviderMessage,
    ProviderRequest,
    ProviderUsage,
)


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
    ) -> None:
        self.provider_id = provider_id
        self.base_url = _validated_base_url(base_url)
        self._headers = dict(headers or {})
        self._client = client
        self._trust_profile = trust_profile
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
            client = create_http_client(profile)

        tool_states: dict[int, _ToolState] = {}
        stop_reason: str | None = None
        terminal_received = False
        try:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers,
                json=build_chat_completions_payload(request),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
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
                            retryable=False,
                            stage="stream",
                        ) from exc
                    if not isinstance(chunk, Mapping):
                        raise ProviderRequestError(
                            f"{self.provider_id} returned an invalid streaming event.",
                            retryable=False,
                            stage="stream",
                        )

                    if isinstance(chunk.get("error"), Mapping):
                        raise ProviderRequestError(
                            f"{self.provider_id} returned a streaming error.",
                            retryable=False,
                            stage="stream",
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
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            stage = _stage_for_status(status)
            raise ProviderRequestError(
                f"{self.provider_id} request failed during {stage} (HTTP {status}).",
                retryable=status in {408, 409, 425, 429} or status >= 500,
                stage=stage,
                status_code=status,
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


def _validated_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderConfigurationError(
            "Provider base URL must be an absolute HTTP(S) URL."
        )
    if parsed.username or parsed.password:
        raise ProviderConfigurationError(
            "Provider base URL must not contain credentials."
        )
    if parsed.query or parsed.fragment:
        raise ProviderConfigurationError(
            "Provider base URL must not contain a query or fragment."
        )
    return normalized


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
