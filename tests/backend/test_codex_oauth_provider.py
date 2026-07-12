from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from openai_codex import ApprovalMode

from lumina.providers import (
    ProviderConfigurationError,
    ProviderMessage,
    ProviderRequest,
)
from lumina.providers.codex import CodexResponsesAdapter
from lumina.providers.codex import adapter as codex_adapter


class _Account:
    def __init__(self, account_type: str = "chatgpt") -> None:
        self.account_type = account_type

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return {"account": {"type": self.account_type, "plan_type": "pro"}}


class TransportClosedError(RuntimeError):
    pass


class _Thread:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    async def run(self, prompt: str, **kwargs: Any) -> object:
        if self.state.get("transport_failures", 0) > 0:
            self.state["transport_failures"] -= 1
            raise TransportClosedError("Codex process closed stdout")
        self.state["prompt"] = prompt
        self.state["run_kwargs"] = kwargs
        return SimpleNamespace(
            final_response=self.state["response"],
            usage=SimpleNamespace(
                last=SimpleNamespace(
                    input_tokens=31,
                    cached_input_tokens=11,
                    output_tokens=7,
                )
            ),
        )


def _fake_async_codex(state: dict[str, Any]) -> type:
    class FakeAsyncCodex:
        def __init__(self, config: object) -> None:
            state["config"] = config
            state["client_count"] = state.get("client_count", 0) + 1

        async def __aenter__(self) -> FakeAsyncCodex:
            state["enter_count"] = state.get("enter_count", 0) + 1
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def close(self) -> None:
            state["close_count"] = state.get("close_count", 0) + 1

        async def account(self) -> _Account:
            state["account_count"] = state.get("account_count", 0) + 1
            return _Account(state.get("account_type", "chatgpt"))

        async def models(self) -> object:
            state["models_count"] = state.get("models_count", 0) + 1
            return SimpleNamespace(
                data=[SimpleNamespace(model="gpt-5.5", hidden=False)]
            )

        async def thread_start(self, **kwargs: Any) -> _Thread:
            state["thread_kwargs"] = kwargs
            return _Thread(state)

    return FakeAsyncCodex


def test_codex_structured_tool_arguments_stream_incrementally() -> None:
    arguments = json.dumps(
        {"path": "game.html", "content": "line one\nline two 한글"},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    envelope = json.dumps(
        {
            "kind": "tool_calls",
            "text": "",
            "tool_calls": [
                {
                    "id": "call_write",
                    "name": "write_file",
                    "arguments_json": arguments,
                }
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    stream = codex_adapter._CodexToolCallStream()
    events = []
    for index in range(0, len(envelope), 13):
        events.extend(stream.feed(envelope[index : index + 13]))

    assert [event.type for event in events].count("tool_call_started") == 1
    deltas = "".join(
        event.arguments_delta or ""
        for event in events
        if event.type == "tool_call_delta"
    )
    assert deltas == arguments
    assert len([event for event in events if event.type == "tool_call_delta"]) > 1


@pytest.mark.asyncio
async def test_codex_oauth_stream_removes_api_keys_and_maps_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {
        "response": json.dumps(
            {"kind": "final", "text": "안녕하세요.", "tool_calls": []},
            ensure_ascii=False,
        )
    }
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-codex")
    monkeypatch.setenv("LUMINA_OPENAI_API_KEY", "must-not-reach-codex")
    monkeypatch.setattr(
        "lumina.providers.codex.adapter.AsyncCodex", _fake_async_codex(state)
    )

    events = [
        event
        async for event in CodexResponsesAdapter().stream(
            ProviderRequest(
                model="gpt-5.5",
                messages=(ProviderMessage(role="user", content="안녕"),),
                effort="low",
                metadata={
                    "prompt_cache_key": "lumina:user:v1:opaque-user-digest"
                },
            )
        )
    ]

    config = state["config"]
    assert "OPENAI_API_KEY" not in config.env
    assert "LUMINA_OPENAI_API_KEY" not in config.env
    assert state["thread_kwargs"]["ephemeral"] is True
    assert state["thread_kwargs"]["approval_mode"] == ApprovalMode.deny_all
    assert (
        "lumina:user:v1:opaque-user-digest"
        in state["thread_kwargs"]["developer_instructions"]
    )
    assert [event.type for event in events] == ["text_delta", "usage", "completed"]
    assert events[0].text == "안녕하세요."
    assert events[1].usage is not None
    assert events[1].usage.uncached_input_tokens == 20
    assert events[1].usage.raw["billing"] == "subscription_usage"


@pytest.mark.asyncio
async def test_codex_oauth_reuses_warm_client_across_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {
        "response": '{"kind":"final","text":"안녕하세요.","tool_calls":[]}'
    }
    monkeypatch.setattr(
        "lumina.providers.codex.adapter.AsyncCodex", _fake_async_codex(state)
    )
    adapter = CodexResponsesAdapter()
    request = ProviderRequest(
        model="gpt-5.5",
        messages=(ProviderMessage(role="user", content="안녕"),),
    )

    for _ in range(2):
        assert [event.type async for event in adapter.stream(request)][-1] == "completed"

    assert state["client_count"] == 1
    assert state["account_count"] == 1
    assert state["models_count"] == 1
    await adapter.close()
    assert state["close_count"] == 1


@pytest.mark.asyncio
async def test_codex_oauth_retries_transport_close_before_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {
        "response": '{"kind":"final","text":"복구됨","tool_calls":[]}',
        "transport_failures": 1,
    }
    monkeypatch.setattr(
        "lumina.providers.codex.adapter.AsyncCodex", _fake_async_codex(state)
    )
    adapter = CodexResponsesAdapter()

    events = [
        event
        async for event in adapter.stream(
            ProviderRequest(
                model="gpt-5.5",
                messages=(ProviderMessage(role="user", content="안녕"),),
            )
        )
    ]

    assert events[0].text == "복구됨"
    assert state["client_count"] == 2
    assert state["close_count"] == 1
    await adapter.close()


@pytest.mark.asyncio
async def test_codex_oauth_stream_maps_lumina_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {
        "response": json.dumps(
            {
                "kind": "tool_calls",
                "text": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "lookup_asset",
                        "arguments_json": '{"asset":"BF-01"}',
                    }
                ],
            }
        )
    }
    monkeypatch.setattr(
        "lumina.providers.codex.adapter.AsyncCodex", _fake_async_codex(state)
    )
    tool = {
        "type": "function",
        "function": {
            "name": "lookup_asset",
            "description": "Lookup an asset",
            "parameters": {"type": "object"},
        },
    }

    events = [
        event
        async for event in CodexResponsesAdapter().stream(
            ProviderRequest(
                model="gpt-5.5",
                messages=(ProviderMessage(role="user", content="BF-01 확인"),),
                tools=(tool,),
            )
        )
    ]

    assert [event.type for event in events] == [
        "tool_call_started",
        "tool_call_delta",
        "tool_call_completed",
        "usage",
        "completed",
    ]
    assert events[2].arguments_json == '{"asset":"BF-01"}'
    assert events[-1].stop_reason == "tool_calls"
    prompt_payload = json.loads(state["prompt"].split("\n", 1)[1])
    assert prompt_payload["tools"][0]["function"]["name"] == "lookup_asset"


@pytest.mark.asyncio
async def test_codex_oauth_requires_chatgpt_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {
        "account_type": "apiKey",
        "response": '{"kind":"final","text":"x","tool_calls":[]}',
    }
    monkeypatch.setattr(
        "lumina.providers.codex.adapter.AsyncCodex", _fake_async_codex(state)
    )

    with pytest.raises(ProviderConfigurationError, match="ChatGPT OAuth"):
        _events = [
            event
            async for event in CodexResponsesAdapter().stream(
                ProviderRequest(
                    model="gpt-5.5",
                    messages=(ProviderMessage(role="user", content="안녕"),),
                )
            )
        ]
