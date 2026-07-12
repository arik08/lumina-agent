from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from lumina.agent.executor import LocalRunExecutor
from lumina.api.routes.providers import _provider_status
from lumina.config import Settings
from lumina.providers import (
    ProviderImage,
    ProviderMessage,
    ProviderRequest,
    ProviderRequestError,
)
from lumina.providers.openai import OpenAIResponsesAdapter, build_responses_payload
from lumina.providers.catalog import initial_model_catalog


def _sse(*events: dict[str, object]) -> bytes:
    return "".join(
        f"event: {event['type']}\n"
        f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
        for event in events
    ).encode("utf-8")


def test_responses_payload_includes_attached_image() -> None:
    payload = build_responses_payload(
        ProviderRequest(
            model="gpt-test",
            messages=(
                ProviderMessage(
                    role="user",
                    content="이 이미지를 읽어 주세요.",
                    images=(ProviderImage("image/png", "cG5n"),),
                ),
            ),
        )
    )

    assert payload["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "이 이미지를 읽어 주세요."},
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,cG5n",
                },
            ],
        }
    ]


def test_responses_payload_routes_prompt_cache_by_opaque_user_key() -> None:
    payload = build_responses_payload(
        ProviderRequest(
            model="gpt-test",
            messages=(ProviderMessage(role="user", content="Hello"),),
            metadata={
                "prompt_cache_key": "lumina:user:v1:opaque-user-digest",
                "prompt_cache_retention": "24h",
            },
        )
    )

    assert payload["prompt_cache_key"] == "lumina:user:v1:opaque-user-digest"
    assert payload["prompt_cache_retention"] == "24h"


def test_responses_payload_uses_modern_cache_ttl_for_gpt_5_6() -> None:
    payload = build_responses_payload(
        ProviderRequest(
            model="gpt-5.6-terra",
            messages=(ProviderMessage(role="user", content="Hello"),),
            metadata={
                "prompt_cache_key": "lumina:user:v1:opaque-user-digest",
                "prompt_cache_retention": "24h",
            },
        )
    )

    assert payload["prompt_cache_options"] == {"ttl": "30m"}
    assert "prompt_cache_retention" not in payload


def test_responses_payload_maps_function_call_round_trip_and_json_schema() -> None:
    payload = build_responses_payload(
        ProviderRequest(
            model="gpt-test",
            messages=(
                ProviderMessage(role="user", content="Inspect BF-01"),
                ProviderMessage(
                    role="assistant",
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
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "inspection_result",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"status": {"type": "string"}},
                        "required": ["status"],
                        "additionalProperties": False,
                    },
                },
            },
        )
    )

    assert payload["input"] == [
        {"role": "user", "content": "Inspect BF-01"},
        {
            "type": "function_call",
            "call_id": "call_previous",
            "name": "lookup_asset",
            "arguments": '{"asset":"BF-01"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_previous",
            "output": '{"status":"ok"}',
        },
    ]
    assert payload["text"] == {
        "format": {
            "type": "json_schema",
            "name": "inspection_result",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
                "additionalProperties": False,
            },
        }
    }


@pytest.mark.asyncio
async def test_openai_responses_streams_text_usage_and_builds_responses_payload() -> (
    None
):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.test/v1/responses"
        assert request.headers["Authorization"] == "Bearer test-openai-key"
        payload = json.loads(request.content)
        assert payload == {
            "model": "gpt-test",
            "input": [
                {"role": "system", "content": "Be precise."},
                {"role": "user", "content": "Hello"},
            ],
            "stream": True,
            "store": False,
            "reasoning": {"effort": "medium"},
            "max_output_tokens": 120,
        }
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                {
                    "type": "response.output_text.delta",
                    "item_id": "msg_1",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "안녕",
                },
                {
                    "type": "response.output_text.delta",
                    "item_id": "msg_1",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "하세요.",
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_1",
                        "status": "completed",
                        "output": [],
                        "usage": {
                            "input_tokens": 10,
                            "input_tokens_details": {"cached_tokens": 3},
                            "output_tokens": 4,
                            "total_tokens": 14,
                        },
                    },
                },
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAIResponsesAdapter(
            api_key="test-openai-key",
            base_url="https://api.openai.test/v1",
            client=client,
        )
        events = [
            event
            async for event in adapter.stream(
                ProviderRequest(
                    model="gpt-test",
                    messages=(
                        ProviderMessage(role="system", content="Be precise."),
                        ProviderMessage(role="user", content="Hello"),
                    ),
                    effort="medium",
                    max_output_tokens=120,
                )
            )
        ]

    assert [event.type for event in events] == [
        "text_delta",
        "text_delta",
        "usage",
        "completed",
    ]
    assert "".join(event.text or "" for event in events) == "안녕하세요."
    usage = events[-2].usage
    assert usage is not None
    assert usage.input_tokens == 10
    assert usage.cached_input_tokens == 3
    assert usage.uncached_input_tokens == 7
    assert usage.output_tokens == 4
    assert events[-1].stop_reason == "stop"


@pytest.mark.asyncio
async def test_openai_responses_streams_function_call_delta_and_done() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tools"] == [
            {
                "type": "function",
                "name": "lookup_asset",
                "description": "Lookup an asset",
                "parameters": {
                    "type": "object",
                    "properties": {"asset": {"type": "string"}},
                    "required": ["asset"],
                },
            }
        ]
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                {
                    "type": "response.output_item.added",
                    "response_id": "resp_tool",
                    "output_index": 0,
                    "item": {
                        "id": "fc_1",
                        "call_id": "call_1",
                        "type": "function_call",
                        "name": "lookup_asset",
                        "arguments": "",
                        "status": "in_progress",
                    },
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "response_id": "resp_tool",
                    "item_id": "fc_1",
                    "output_index": 0,
                    "delta": '{"asset":',
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "response_id": "resp_tool",
                    "item_id": "fc_1",
                    "output_index": 0,
                    "delta": '"BF-01"}',
                },
                {
                    "type": "response.function_call_arguments.done",
                    "response_id": "resp_tool",
                    "item_id": "fc_1",
                    "output_index": 0,
                    "name": "lookup_asset",
                    "arguments": '{"asset":"BF-01"}',
                },
                {
                    "type": "response.output_item.done",
                    "response_id": "resp_tool",
                    "output_index": 0,
                    "item": {
                        "id": "fc_1",
                        "call_id": "call_1",
                        "type": "function_call",
                        "name": "lookup_asset",
                        "arguments": '{"asset":"BF-01"}',
                        "status": "completed",
                    },
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_tool",
                        "status": "completed",
                        "output": [
                            {
                                "id": "fc_1",
                                "call_id": "call_1",
                                "type": "function_call",
                                "name": "lookup_asset",
                                "arguments": '{"asset":"BF-01"}',
                                "status": "completed",
                            }
                        ],
                        "usage": {
                            "input_tokens": 20,
                            "output_tokens": 8,
                            "total_tokens": 28,
                        },
                    },
                },
            ),
        )

    tool = {
        "type": "function",
        "function": {
            "name": "lookup_asset",
            "description": "Lookup an asset",
            "parameters": {
                "type": "object",
                "properties": {"asset": {"type": "string"}},
                "required": ["asset"],
            },
        },
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAIResponsesAdapter(
            api_key="test-openai-key",
            base_url="https://api.openai.test/v1",
            client=client,
        )
        events = [
            event
            async for event in adapter.stream(
                ProviderRequest(
                    model="gpt-test",
                    messages=(ProviderMessage(role="user", content="Find BF-01"),),
                    tools=(tool,),
                )
            )
        ]

    assert [event.type for event in events] == [
        "tool_call_started",
        "tool_call_delta",
        "tool_call_delta",
        "tool_call_completed",
        "usage",
        "completed",
    ]
    assert {event.tool_call_id for event in events[:4]} == {"call_1"}
    assert events[0].tool_name == "lookup_asset"
    assert events[3].arguments_json == '{"asset":"BF-01"}'
    assert events[-1].stop_reason == "tool_calls"


@pytest.mark.asyncio
async def test_openai_responses_stream_error_is_typed_retryable_and_redacted() -> None:
    secret_from_remote_message = "sk-should-never-escape"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                {
                    "type": "error",
                    "code": "rate_limit_exceeded",
                    "message": f"remote echoed {secret_from_remote_message}",
                    "param": None,
                }
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAIResponsesAdapter(
            api_key="test-openai-key",
            base_url="https://api.openai.test/v1",
            client=client,
        )
        with pytest.raises(ProviderRequestError) as captured:
            _events = [
                event
                async for event in adapter.stream(
                    ProviderRequest(
                        model="gpt-test",
                        messages=(ProviderMessage(role="user", content="Hello"),),
                    )
                )
            ]

    assert captured.value.retryable is True
    assert captured.value.stage == "stream"
    assert "rate_limit_exceeded" in str(captured.value)
    assert secret_from_remote_message not in str(captured.value)


def test_openai_provider_ready_catalog_and_executor_selection(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'openai.db').as_posix()}",
        data_dir=tmp_path,
        openai_api_key="test-openai-key",
        openai_base_url="https://gateway.openai.test/v1",
    )

    assert _provider_status("openai", settings) == "ready"
    catalog = initial_model_catalog("openai")
    assert len(catalog) == 3
    assert sum(model.is_default for model in catalog) == 1
    adapter = LocalRunExecutor(settings)._provider(
        "openai", wants_artifact=False, first_turn=True
    )
    assert isinstance(adapter, OpenAIResponsesAdapter)
    assert adapter.base_url == "https://gateway.openai.test/v1"
    assert "test-openai-key" not in repr(settings)
