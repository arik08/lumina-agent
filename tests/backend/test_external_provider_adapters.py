from __future__ import annotations

import asyncio
import json
import ssl
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from lumina.agent.executor import (
    LocalRunExecutor,
    _safe_provider_metadata,
    local_run_executor,
)
from lumina.api.routes.providers import _provider_status
from lumina.config import Settings
from lumina.main import create_app
from lumina.http_client import TrustProfile
from lumina.providers import (
    ProviderCapabilities,
    ProviderEvent,
    ProviderImage,
    ProviderMessage,
    ProviderRequest,
    ProviderRequestError,
)
from lumina.providers.anthropic import (
    AnthropicMessagesAdapter,
    build_anthropic_payload,
)
from lumina.providers.google import GoogleGeminiAdapter, build_google_payload
from lumina.providers.openai_compatible import (
    OpenAICompatibleAdapter,
    build_chat_completions_payload,
)
from lumina.providers.codex import CodexResponsesAdapter
from lumina.providers.pgpt import (
    PgptAdapter,
    PgptCredentials,
    PgptProfile,
    build_pgpt_payload,
)


_TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_asset",
        "description": "Lookup an asset",
        "parameters": {
            "type": "object",
            "properties": {"asset": {"type": "string"}},
            "required": ["asset"],
            "additionalProperties": False,
        },
    },
}


def _sse(*events: dict[str, object]) -> bytes:
    return "".join(
        f"event: {event.get('type', 'message')}\n"
        f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
        for event in events
    ).encode("utf-8")


def _google_sse(*chunks: dict[str, object]) -> bytes:
    return "".join(
        f"data: {json.dumps(chunk, ensure_ascii=False, separators=(',', ':'))}\n\n"
        for chunk in chunks
    ).encode("utf-8")


def _openai_sse(*chunks: dict[str, object]) -> bytes:
    return (
        "".join(
            f"data: {json.dumps(chunk, ensure_ascii=False, separators=(',', ':'))}\n\n"
            for chunk in chunks
        )
        + "data: [DONE]\n\n"
    ).encode("utf-8")


def test_multimodal_payloads_include_attached_image() -> None:
    request = ProviderRequest(
        model="vision-test",
        messages=(
            ProviderMessage(
                role="user",
                content="이미지를 읽어 주세요.",
                images=(ProviderImage("image/png", "cG5n"),),
            ),
        ),
    )

    anthropic = build_anthropic_payload(request)
    assert anthropic["messages"][0]["content"][0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "cG5n"},
    }
    google = build_google_payload(request)
    assert google["contents"][0]["parts"][0] == {
        "inlineData": {"mimeType": "image/png", "data": "cG5n"}
    }
    compatible = build_chat_completions_payload(request)
    assert compatible["messages"][0]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,cG5n"},
    }


def test_anthropic_payload_maps_system_tool_call_and_tool_result() -> None:
    payload = build_anthropic_payload(
        ProviderRequest(
            model="claude-test",
            messages=(
                ProviderMessage(role="system", content="Be precise."),
                ProviderMessage(role="user", content="Inspect BF-01"),
                ProviderMessage(
                    role="assistant",
                    content="확인하겠습니다.",
                    tool_calls=(
                        {
                            "id": "call_previous",
                            "type": "function",
                            "function": {
                                "name": "lookup_asset",
                                "arguments": '{"asset":"BF-01"}',
                            },
                        },
                    ),
                ),
                ProviderMessage(
                    role="tool",
                    tool_call_id="call_previous",
                    name="lookup_asset",
                    content='{"status":"ok"}',
                ),
            ),
            tools=(_TOOL,),
            max_output_tokens=512,
            temperature=0.2,
        )
    )

    assert payload == {
        "model": "claude-test",
        "messages": [
            {"role": "user", "content": "Inspect BF-01"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "확인하겠습니다."},
                    {
                        "type": "tool_use",
                        "id": "call_previous",
                        "name": "lookup_asset",
                        "input": {"asset": "BF-01"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_previous",
                        "content": '{"status":"ok"}',
                    }
                ],
            },
        ],
        "max_tokens": 512,
        "stream": True,
        "system": "Be precise.",
        "tools": [
            {
                "name": "lookup_asset",
                "description": "Lookup an asset",
                "input_schema": _TOOL["function"]["parameters"],
            }
        ],
        "temperature": 0.2,
    }


@pytest.mark.asyncio
async def test_anthropic_stream_normalizes_text_tool_usage_and_completion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://anthropic.test/v1/messages"
        assert request.headers["x-api-key"] == "anthropic-secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        payload = json.loads(request.content)
        assert payload["tools"][0]["name"] == "lookup_asset"
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                {
                    "type": "message_start",
                    "message": {
                        "usage": {
                            "input_tokens": 5,
                            "cache_read_input_tokens": 3,
                            "cache_creation_input_tokens": 2,
                            "output_tokens": 1,
                        }
                    },
                },
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "확인했습니다."},
                },
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "call_anthropic",
                        "name": "lookup_asset",
                        "input": {},
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"asset":',
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '"BF-01"}',
                    },
                },
                {"type": "content_block_stop", "index": 1},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"output_tokens": 7},
                },
                {"type": "message_stop"},
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = AnthropicMessagesAdapter(
            api_key="anthropic-secret",
            base_url="https://anthropic.test/v1",
            client=client,
        )
        events = [
            event
            async for event in adapter.stream(
                ProviderRequest(
                    model="claude-test",
                    messages=(ProviderMessage(role="user", content="Inspect"),),
                    tools=(_TOOL,),
                )
            )
        ]

    assert [event.type for event in events] == [
        "text_delta",
        "tool_call_started",
        "tool_call_delta",
        "tool_call_delta",
        "tool_call_completed",
        "usage",
        "completed",
    ]
    assert events[4].arguments_json == '{"asset":"BF-01"}'
    usage = events[-2].usage
    assert usage is not None
    assert usage.input_tokens == 10
    assert usage.cached_input_tokens == 3
    assert usage.cache_write_tokens == 2
    assert usage.uncached_input_tokens == 5
    assert usage.output_tokens == 7
    assert events[-1].stop_reason == "tool_calls"


@pytest.mark.asyncio
async def test_anthropic_stream_error_is_typed_and_does_not_expose_remote_body() -> (
    None
):
    leaked = "remote-secret-must-not-escape"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                {
                    "type": "error",
                    "error": {"type": "overloaded_error", "message": leaked},
                }
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = AnthropicMessagesAdapter(api_key="key", client=client)
        with pytest.raises(ProviderRequestError) as captured:
            _events = [
                event
                async for event in adapter.stream(
                    ProviderRequest(
                        model="claude-test",
                        messages=(ProviderMessage(role="user", content="Hello"),),
                    )
                )
            ]

    assert captured.value.retryable is True
    assert captured.value.stage == "stream"
    assert "overloaded_error" in str(captured.value)
    assert leaked not in str(captured.value)


def test_google_payload_maps_system_tool_roundtrip_and_thought_signature() -> None:
    request = ProviderRequest(
        model="gemini-test",
        messages=(
            ProviderMessage(role="system", content="Be precise."),
            ProviderMessage(role="user", content="Inspect BF-01"),
            ProviderMessage(
                role="assistant",
                tool_calls=(
                    {
                        "id": "call_google",
                        "type": "function",
                        "function": {
                            "name": "lookup_asset",
                            "arguments": '{"asset":"BF-01"}',
                        },
                    },
                ),
                provider_metadata={
                    "call_google": {"thought_signature": "signed-thought"}
                },
            ),
            ProviderMessage(
                role="tool",
                tool_call_id="call_google",
                name="lookup_asset",
                content='{"status":"ok"}',
                provider_metadata={"thought_signature": "signed-thought"},
            ),
        ),
        tools=(_TOOL,),
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "result",
                "schema": {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                },
            },
        },
        max_output_tokens=256,
    )
    payload = build_google_payload(request)

    assert payload["systemInstruction"] == {"parts": [{"text": "Be precise."}]}
    assert payload["contents"][1] == {
        "role": "model",
        "parts": [
            {
                "functionCall": {
                    "id": "call_google",
                    "name": "lookup_asset",
                    "args": {"asset": "BF-01"},
                },
                "thoughtSignature": "signed-thought",
            }
        ],
    }
    assert payload["contents"][2] == {
        "role": "user",
        "parts": [
            {
                "functionResponse": {
                    "id": "call_google",
                    "name": "lookup_asset",
                    "response": {"status": "ok"},
                }
            }
        ],
    }
    assert payload["tools"] == [
        {
            "functionDeclarations": [
                {
                    "name": "lookup_asset",
                    "description": "Lookup an asset",
                    "parametersJsonSchema": _TOOL["function"]["parameters"],
                }
            ]
        }
    ]
    assert payload["generationConfig"] == {
        "maxOutputTokens": 256,
        "responseMimeType": "application/json",
        "responseJsonSchema": {
            "type": "object",
            "properties": {"status": {"type": "string"}},
        },
    }


@pytest.mark.asyncio
async def test_google_stream_normalizes_text_tool_usage_and_completion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == (
            "https://google.test/v1beta/models/gemini-test:streamGenerateContent?alt=sse"
        )
        assert request.headers["x-goog-api-key"] == "google-secret"
        payload = json.loads(request.content)
        assert payload["tools"][0]["functionDeclarations"][0]["name"] == (
            "lookup_asset"
        )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_google_sse(
                {
                    "candidates": [
                        {
                            "index": 0,
                            "content": {
                                "role": "model",
                                "parts": [{"text": "확인했습니다."}],
                            },
                        }
                    ]
                },
                {
                    "candidates": [
                        {
                            "index": 0,
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "functionCall": {
                                            "id": "call_google",
                                            "name": "lookup_asset",
                                            "args": {"asset": "BF-01"},
                                        },
                                        "thoughtSignature": "signed-thought",
                                    }
                                ],
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 10,
                        "cachedContentTokenCount": 4,
                        "candidatesTokenCount": 3,
                        "thoughtsTokenCount": 2,
                        "totalTokenCount": 15,
                    },
                },
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = GoogleGeminiAdapter(
            api_key="google-secret",
            base_url="https://google.test/v1beta",
            client=client,
        )
        events = [
            event
            async for event in adapter.stream(
                ProviderRequest(
                    model="gemini-test",
                    messages=(ProviderMessage(role="user", content="Inspect"),),
                    tools=(_TOOL,),
                )
            )
        ]

    assert [event.type for event in events] == [
        "text_delta",
        "tool_call_started",
        "tool_call_delta",
        "tool_call_completed",
        "usage",
        "completed",
    ]
    assert events[1].provider_metadata == {"thought_signature": "signed-thought"}
    assert events[3].arguments_json == '{"asset":"BF-01"}'
    assert events[3].provider_metadata == {"thought_signature": "signed-thought"}
    usage = events[-2].usage
    assert usage is not None
    assert usage.input_tokens == 10
    assert usage.cached_input_tokens == 4
    assert usage.uncached_input_tokens == 6
    assert usage.output_tokens == 5
    assert events[-1].stop_reason == "tool_calls"


@pytest.mark.asyncio
async def test_google_stream_error_is_typed_and_does_not_expose_remote_body() -> None:
    leaked = "google-remote-secret"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_google_sse(
                {
                    "error": {
                        "code": 503,
                        "status": "UNAVAILABLE",
                        "message": leaked,
                    }
                }
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = GoogleGeminiAdapter(api_key="key", client=client)
        with pytest.raises(ProviderRequestError) as captured:
            _events = [
                event
                async for event in adapter.stream(
                    ProviderRequest(
                        model="gemini-test",
                        messages=(ProviderMessage(role="user", content="Hello"),),
                    )
                )
            ]

    assert captured.value.retryable is True
    assert captured.value.stage == "stream"
    assert "UNAVAILABLE" in str(captured.value)
    assert leaked not in str(captured.value)


@pytest.mark.asyncio
async def test_openai_compatible_stream_and_discovery_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer compatible-secret"
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {"id": "model-a"},
                        {"id": "model-b"},
                        {"id": "model-a"},
                    ],
                },
            )
        assert request.url.path.endswith("/chat/completions")
        payload = json.loads(request.content)
        assert payload["stream_options"] == {"include_usage": True}
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_openai_sse(
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "확인했습니다."},
                            "finish_reason": None,
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_compatible",
                                        "function": {
                                            "name": "lookup_asset",
                                            "arguments": '{"asset":',
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": '"BF-01"}'},
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 12,
                        "prompt_tokens_details": {"cached_tokens": 5},
                        "completion_tokens": 4,
                    },
                },
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleAdapter(
            provider_id="openai_compatible",
            base_url="https://compatible.test/v1",
            headers={"Authorization": "Bearer compatible-secret"},
            client=client,
        )
        models = await adapter.discover_models()
        events = [
            event
            async for event in adapter.stream(
                ProviderRequest(
                    model="model-a",
                    messages=(ProviderMessage(role="user", content="Inspect"),),
                    tools=(_TOOL,),
                )
            )
        ]

    assert models == ("model-a", "model-b")
    assert [event.type for event in events] == [
        "text_delta",
        "tool_call_started",
        "tool_call_delta",
        "tool_call_delta",
        "usage",
        "tool_call_completed",
        "completed",
    ]
    assert events[-2].arguments_json == '{"asset":"BF-01"}'
    usage = events[-3].usage
    assert usage is not None
    assert usage.input_tokens == 12
    assert usage.cached_input_tokens == 5
    assert usage.uncached_input_tokens == 7
    assert usage.output_tokens == 4


@pytest.mark.asyncio
async def test_openai_compatible_http_error_is_redacted() -> None:
    leaked = "remote-compatible-secret"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": leaked}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleAdapter(
            provider_id="openai_compatible",
            base_url="https://compatible.test/v1",
            headers={"Authorization": "Bearer local-secret"},
            client=client,
        )
        with pytest.raises(ProviderRequestError) as captured:
            _events = [
                event
                async for event in adapter.stream(
                    ProviderRequest(
                        model="model-a",
                        messages=(ProviderMessage(role="user", content="Hello"),),
                    )
                )
            ]

    assert captured.value.status_code == 401
    assert captured.value.stage == "authentication"
    assert leaked not in str(captured.value)
    assert "local-secret" not in str(captured.value)


@pytest.mark.asyncio
async def test_openai_compatible_rejects_non_object_stream_events() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=b'data: ["unexpected"]\n\n',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleAdapter(
            provider_id="openai_compatible",
            base_url="https://compatible.test/v1",
            headers={"Authorization": "Bearer local-secret"},
            client=client,
        )
        with pytest.raises(ProviderRequestError) as captured:
            _events = [
                event
                async for event in adapter.stream(
                    ProviderRequest(
                        model="model-a",
                        messages=(ProviderMessage(role="user", content="Hello"),),
                    )
                )
            ]

    assert captured.value.stage == "stream"
    assert captured.value.retryable is True


@pytest.mark.asyncio
async def test_openai_compatible_accepts_multiline_sse_and_raw_json_lines() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=(
                b'data: {"choices":[\n'
                b'data: {"delta":{"content":"multi"},"finish_reason":null}]}\n\n'
                b'{"choices":[{"delta":{"content":"line"},"finish_reason":"stop"}]}\n'
                b'data: [DONE]\n\n'
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleAdapter(
            provider_id="openai_compatible",
            base_url="https://compatible.test/v1",
            headers={"Authorization": "Bearer local-secret"},
            client=client,
        )
        events = [
            event
            async for event in adapter.stream(
                ProviderRequest(
                    model="model-a",
                    messages=(ProviderMessage(role="user", content="Hello"),),
                )
            )
        ]

    assert [event.text for event in events if event.type == "text_delta"] == [
        "multi",
        "line",
    ]
    assert events[-1].type == "completed"


@pytest.mark.asyncio
async def test_openai_compatible_marks_transient_stream_error_retryable() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=b'data: {"error":{"code":"rate_limit","status":429}}\n\n',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleAdapter(
            provider_id="openai_compatible",
            base_url="https://compatible.test/v1",
            headers={"Authorization": "Bearer local-secret"},
            client=client,
        )
        with pytest.raises(ProviderRequestError) as captured:
            _ = [
                event
                async for event in adapter.stream(
                    ProviderRequest(
                        model="model-a",
                        messages=(ProviderMessage(role="user", content="Hello"),),
                    )
                )
            ]

    assert captured.value.stage == "stream"
    assert captured.value.retryable is True


def test_provider_settings_ready_status_executor_and_codex_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'providers.db').as_posix()}",
        data_dir=tmp_path,
        anthropic_api_key="anthropic-secret",
        anthropic_base_url="https://anthropic.test/v1",
        google_api_key="google-secret",
        google_base_url="https://google.test/v1beta",
        openai_compatible_api_key="compatible-secret",
        openai_compatible_base_url="https://compatible.test/v1",
        openai_api_key="",
        pgpt_api_key="pgpt-secret",
        pgpt_employee_no="employee-secret",
        pgpt_company_code="30",
        pgpt_base_url="https://pgpt.test/v1",
    )

    assert _provider_status("pgpt", settings) == "ready"
    assert _provider_status("anthropic", settings) == "ready"
    assert _provider_status("google", settings) == "ready"
    assert _provider_status("openai_compatible", settings) == "ready"
    monkeypatch.setattr(
        "lumina.api.routes.providers.codex_oauth_available", lambda: True
    )
    assert _provider_status("codex", settings) == "ready"
    executor = LocalRunExecutor(settings)
    assert isinstance(
        executor._provider("pgpt", wants_artifact=False, first_turn=True),
        PgptAdapter,
    )
    assert executor._provider(
        "pgpt", wants_artifact=False, first_turn=True
    ) is executor._provider("pgpt", wants_artifact=False, first_turn=False)
    assert isinstance(
        executor._provider("anthropic", wants_artifact=False, first_turn=True),
        AnthropicMessagesAdapter,
    )
    assert isinstance(
        executor._provider("google", wants_artifact=False, first_turn=True),
        GoogleGeminiAdapter,
    )
    assert isinstance(
        executor._provider("openai_compatible", wants_artifact=False, first_turn=True),
        OpenAICompatibleAdapter,
    )
    assert isinstance(
        executor._provider("codex", wants_artifact=False, first_turn=True),
        CodexResponsesAdapter,
    )
    monkeypatch.setattr(
        "lumina.api.routes.providers.codex_oauth_available", lambda: False
    )
    assert _provider_status("codex", settings) == "needs_setup"
    representation = repr(settings)
    assert "anthropic-secret" not in representation
    assert "google-secret" not in representation
    assert "compatible-secret" not in representation
    assert "pgpt-secret" not in representation
    assert "employee-secret" not in representation
    invalid = settings.model_copy(
        update={"openai_compatible_base_url": "https://user:pass@example.test/v1"}
    )
    assert _provider_status("openai_compatible", invalid) == "needs_setup"


def test_pgpt_settings_load_from_dotenv_for_status_and_execution(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PGPT_API_KEY=dotenv-key\n"
        "PGPT_EMPLOYEE_NO=dotenv-employee\n"
        "PGPT_COMPANY_CODE=30\n",
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=env_file,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'dotenv.db').as_posix()}",
        data_dir=tmp_path,
    )

    assert _provider_status("pgpt", settings) == "ready"
    assert isinstance(
        LocalRunExecutor(settings)._provider(
            "pgpt", wants_artifact=False, first_turn=True
        ),
        PgptAdapter,
    )


@pytest.mark.asyncio
async def test_pgpt_adapter_uses_streaming_cache_payload_and_normalizes_response() -> (
    None
):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://pgpt.test/v1/chat/completions"
        assert request.headers["accept"] == "text/event-stream"
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert payload["stream_options"] == {"include_usage": True}
        assert payload["prompt_cache_key"] == "lumina:user:v1:opaque"
        assert payload["prompt_cache_retention"] == "24h"
        assert payload["max_completion_tokens"] == 42_000
        assert "response_format" not in payload
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_openai_sse(
                {"choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}]},
                {"usage": {"prompt_tokens": 4, "completion_tokens": 1}},
            )
            + b"data: [DONE]\n\n",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        profile = PgptProfile(base_url="https://pgpt.test/v1")
        assert profile.timeout_seconds == 180.0
        adapter = PgptAdapter(
            profile=profile,
            credentials=PgptCredentials(
                api_key="pgpt-key",
                employee_no="employee-no",
                company_code="30",
            ),
            client=client,
        )
        events = [
            event
            async for event in adapter.stream(
                ProviderRequest(
                    model="gpt-5.4",
                    messages=(ProviderMessage(role="user", content="Hello"),),
                    max_output_tokens=42_000,
                    response_format={"type": "json_object"},
                    metadata={
                        "prompt_cache_key": "lumina:user:v1:opaque",
                        "prompt_cache_retention": "24h",
                    },
                )
            )
        ]

    assert [event.text for event in events if event.type == "text_delta"] == ["OK"]
    assert (
        next(event for event in events if event.type == "usage").usage.input_tokens == 4
    )


@pytest.mark.asyncio
async def test_pgpt_adapter_negotiates_rejected_optional_cache_fields() -> None:
    payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(
                400,
                json={"error": {"message": "Unsupported parameter: prompt_cache_key"}},
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_openai_sse(
                {"choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}]}
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = PgptAdapter(
            profile=PgptProfile(base_url="https://pgpt.test/v1"),
            credentials=PgptCredentials(
                api_key="pgpt-key",
                employee_no="employee-no",
                company_code="30",
            ),
            client=client,
        )
        events = [
            event
            async for event in adapter.stream(
                ProviderRequest(
                    model="gpt-5.4",
                    messages=(ProviderMessage(role="user", content="Hello"),),
                    metadata={
                        "prompt_cache_key": "lumina:user:v1:opaque",
                        "prompt_cache_retention": "24h",
                    },
                )
            )
        ]

    assert len(payloads) == 2
    assert payloads[0]["prompt_cache_key"] == "lumina:user:v1:opaque"
    assert "prompt_cache_key" not in payloads[1]
    assert "prompt_cache_retention" not in payloads[1]
    assert events[-1].type == "completed"


@pytest.mark.asyncio
async def test_pgpt_optional_negotiation_is_safe_for_concurrent_runs() -> None:
    first_wave = 0
    all_initial_requests_started = asyncio.Event()
    payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_wave
        payload = json.loads(request.content)
        payloads.append(payload)
        if "prompt_cache_key" in payload:
            first_wave += 1
            if first_wave == 2:
                all_initial_requests_started.set()
            await asyncio.wait_for(all_initial_requests_started.wait(), timeout=1)
            return httpx.Response(
                400,
                json={"error": {"message": "Unsupported parameter: prompt_cache_key"}},
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_openai_sse(
                {"choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}]}
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = PgptAdapter(
            profile=PgptProfile(base_url="https://pgpt.test/v1"),
            credentials=PgptCredentials(
                api_key="pgpt-key",
                employee_no="employee-no",
                company_code="30",
            ),
            client=client,
        )
        request = ProviderRequest(
            model="gpt-5.4",
            messages=(ProviderMessage(role="user", content="Hello"),),
            metadata={"prompt_cache_key": "lumina:user:v1:opaque"},
        )

        async def collect() -> list[ProviderEvent]:
            return [event async for event in adapter.stream(request)]

        results = await asyncio.gather(collect(), collect())

    assert first_wave == 2
    assert len(payloads) == 4
    assert all(events[-1].type == "completed" for events in results)
    assert all("prompt_cache_key" not in payload for payload in payloads[2:])


@pytest.mark.asyncio
async def test_pgpt_adapter_reuses_owned_http_client_until_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_openai_sse(
                {"choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}]}
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    created_clients: list[httpx.AsyncClient] = []

    def create_client(*_args: object, **_kwargs: object) -> httpx.AsyncClient:
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        "lumina.providers.pgpt.adapter.create_http_client", create_client
    )
    adapter = PgptAdapter(
        profile=PgptProfile(base_url="https://pgpt.test/v1"),
        credentials=PgptCredentials(
            api_key="pgpt-key",
            employee_no="employee-no",
            company_code="30",
        ),
        trust_profile=TrustProfile(
            ssl_context=ssl.create_default_context(),
            bundle_path=None,
            company_ca_path=None,
            source="test",
        ),
    )
    request = ProviderRequest(
        model="gpt-5.4",
        messages=(ProviderMessage(role="user", content="Hello"),),
    )

    for _attempt in range(2):
        assert [event.type async for event in adapter.stream(request)][
            -1
        ] == "completed"

    assert request_count == 2
    assert created_clients == [client]
    await adapter.close()
    assert client.is_closed is True


def test_pgpt_payload_uses_myharness_interactive_output_cap_by_default() -> None:
    payload = build_pgpt_payload(
        ProviderRequest(
            model="gpt-5.4",
            messages=(ProviderMessage(role="user", content="Hello"),),
        )
    )

    assert payload["max_completion_tokens"] == 42_000


@pytest.mark.asyncio
async def test_pgpt_adapter_classifies_context_overflow_without_exposing_body() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "context_length_exceeded",
                    "message": "input exceeds the context window",
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = PgptAdapter(
            profile=PgptProfile(base_url="https://pgpt.test/v1"),
            credentials=PgptCredentials(
                api_key="pgpt-key",
                employee_no="employee-no",
                company_code="30",
            ),
            client=client,
        )
        with pytest.raises(ProviderRequestError) as captured:
            _ = [
                event
                async for event in adapter.stream(
                    ProviderRequest(
                        model="gpt-5.4",
                        messages=(ProviderMessage(role="user", content="Hello"),),
                    )
                )
            ]

    assert captured.value.stage == "context"
    assert captured.value.status_code == 400
    assert "input exceeds" not in str(captured.value)


def test_openai_compatible_discovery_never_auto_activates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'catalog.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
        openai_compatible_api_key="compatible-secret",
        openai_compatible_base_url="https://compatible.test/v1",
    )

    async def fake_discovery(_adapter: OpenAICompatibleAdapter) -> tuple[str, ...]:
        return ("remote-model-a", "remote-model-b")

    monkeypatch.setattr(OpenAICompatibleAdapter, "discover_models", fake_discovery)
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        discovered = client.post(
            "/api/admin/providers/openai_compatible/models/discover",
            headers={"X-CSRF-Token": csrf},
        )
        assert discovered.status_code == 200, discovered.text
        assert discovered.json()["autoActivated"] is False
        assert {item["status"] for item in discovered.json()["items"]} == {"discovered"}
        assert client.get("/api/admin/providers/openai_compatible/models").json() == []

        created = client.post(
            "/api/admin/providers/openai_compatible/models",
            headers={"X-CSRF-Token": csrf},
            json={
                "modelKey": "approved-model",
                "displayName": "Approved Model",
                "runtimeModelId": "remote-model-a",
                "enabled": True,
                "isDefault": True,
                "capabilities": {"tools": True},
            },
        )
        assert created.status_code == 201, created.text
        discovered_again = client.post(
            "/api/admin/providers/openai_compatible/models/discover",
            headers={"X-CSRF-Token": csrf},
        )
        first = discovered_again.json()["items"][0]
        assert first["modelKey"] == "approved-model"
        assert first["status"] == "active"
        assert first["activationRequired"] is False
        providers = client.get("/api/providers").json()
        compatible = next(
            item for item in providers if item["id"] == "openai_compatible"
        )
        assert compatible["connectionStatus"] == "ready"


def test_provider_metadata_is_allowlisted_and_size_bounded() -> None:
    assert _safe_provider_metadata(
        {
            "thought_signature": "signed-thought",
            "raw_response": {"credential": "must-not-pass"},
        }
    ) == {"thought_signature": "signed-thought"}
    assert _safe_provider_metadata({"thought_signature": "x" * 16_385}) == {}


class _CapturingGeminiProvider:
    provider_id = "google"
    capabilities = ProviderCapabilities(tools=True)

    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        if len(self.requests) == 1:
            arguments = json.dumps(
                {
                    "format": "html",
                    "title": "왕복 테스트",
                    "executive_summary": "서명 왕복을 확인합니다.",
                    "sections": [],
                    "action_items": [],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            metadata = {
                "thought_signature": "executor-signed-thought",
                "raw_response": "must-not-pass",
            }
            yield ProviderEvent(
                type="tool_call_started",
                tool_call_id="call_report",
                tool_name="create_report",
                provider_metadata=metadata,
            )
            yield ProviderEvent(
                type="tool_call_delta",
                tool_call_id="call_report",
                tool_name="create_report",
                arguments_delta=arguments,
                provider_metadata=metadata,
            )
            yield ProviderEvent(
                type="tool_call_completed",
                tool_call_id="call_report",
                tool_name="create_report",
                arguments_json=arguments,
                provider_metadata=metadata,
            )
            yield ProviderEvent(type="completed", stop_reason="tool_calls")
            return
        yield ProviderEvent(type="text_delta", text="완료했습니다.")
        yield ProviderEvent(type="completed", stop_reason="stop")


def test_executor_preserves_gemini_thought_signature_through_tool_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'roundtrip.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
        google_api_key="google-secret",
    )
    capturing = _CapturingGeminiProvider()

    def fake_provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> _CapturingGeminiProvider:
        del wants_artifact, first_turn
        return capturing

    monkeypatch.setattr(local_run_executor, "_provider", fake_provider)
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "Gemini metadata roundtrip"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "gemini-metadata-roundtrip-0001",
            },
            json={
                "message": {
                    "text": "설비 결과를 보고서로 만들어 주세요.",
                    "attachmentIds": [],
                    "promptReferences": [],
                },
                "execution": {
                    "providerId": "google",
                    "modelKey": "gemini-3.1-pro",
                    "effortId": "medium",
                },
            },
        )
        assert started.status_code == 202, started.text
        snapshot = _wait_for_terminal(client, started.json()["run"]["runId"])
        assert snapshot["status"] == "completed"

    conversation_requests = [
        request
        for request in capturing.requests
        if request.metadata.get("purpose") != "user_memory_extraction"
    ]
    assert len(conversation_requests) == 2
    second = conversation_requests[1]
    assistant = next(message for message in second.messages if message.tool_calls)
    tool_result = next(message for message in second.messages if message.role == "tool")
    assert assistant.provider_metadata == {
        "call_report": {"thought_signature": "executor-signed-thought"}
    }
    assert tool_result.provider_metadata == {
        "thought_signature": "executor-signed-thought"
    }
    payload = build_google_payload(second)
    function_call_part = next(
        part
        for content in payload["contents"]
        for part in content["parts"]
        if "functionCall" in part
    )
    function_response_part = next(
        part
        for content in payload["contents"]
        for part in content["parts"]
        if "functionResponse" in part
    )
    assert function_call_part["thoughtSignature"] == "executor-signed-thought"
    assert function_response_part["functionResponse"]["id"] == "call_report"


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "admin",
            "loginDomain": "posco.com",
            "password": "1",
        },
    )
    assert response.status_code == 200
    return response.json()["csrfToken"]


def _wait_for_terminal(client: TestClient, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}/snapshot")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {
            "completed",
            "failed",
            "cancelled",
            "limit_reached",
            "interrupted",
        }:
            return payload
        time.sleep(0.03)
    raise AssertionError("Run did not reach a terminal state")
