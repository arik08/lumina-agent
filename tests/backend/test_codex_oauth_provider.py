from __future__ import annotations

import json
import os
import base64
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai_codex import ApprovalMode

from lumina.providers import (
    ProviderConfigurationError,
    ProviderMessage,
    ProviderRequest,
    ProviderRequestError,
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


def _test_codex_token(account_id: str = "acct-test") -> str:
    header = base64.urlsafe_b64encode(b'{}').decode().rstrip("=")
    claims = base64.urlsafe_b64encode(
        json.dumps(
            {
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": account_id
                }
            }
        ).encode()
    ).decode().rstrip("=")
    return f"{header}.{claims}.signature"


@pytest.mark.asyncio
async def test_codex_direct_routes_same_prefix_across_new_run_sessions(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(
        json.dumps({"tokens": {"access_token": _test_codex_token()}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    captured: list[tuple[httpx.Headers, dict[str, Any]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.append((request.headers, payload))
        response = {
            "type": "response.completed",
            "response": {
                "output": [],
                "usage": {
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 85},
                    "output_tokens": 4,
                },
            },
        }
        body = f"data: {json.dumps(response)}\n\n".encode()
        return httpx.Response(200, content=body)

    adapter = CodexResponsesAdapter()
    adapter._responses_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    fake_client = SimpleNamespace()

    async def ready_client():
        return fake_client, frozenset({"gpt-5.5"}), "."

    monkeypatch.setattr(adapter, "_ready_client", ready_client)
    cache_key = "lumina:user:v2:shared-static-prefix"
    for run_id, task in (("session-a", "first task"), ("session-b", "next task")):
        events = [
            event
            async for event in adapter.stream(
                ProviderRequest(
                    model="gpt-5.5",
                    messages=(
                        ProviderMessage(role="system", content="stable system"),
                        ProviderMessage(role="user", content=task),
                    ),
                    metadata={
                        "prompt_cache_key": cache_key,
                        "prompt_cache_retention": "24h",
                        "codex_run_thread_id": run_id,
                    },
                    max_output_tokens=32,
                    temperature=0.2,
                )
            )
        ]
        assert events[-2].usage is not None
        assert events[-2].usage.cached_input_tokens == 85
        assert events[-2].usage.raw["billing"] == "subscription_usage"

    assert len(captured) == 2
    assert captured[0][0]["session_id"] == captured[1][0]["session_id"]
    assert captured[0][0]["chatgpt-account-id"] == "acct-test"
    assert captured[0][1]["prompt_cache_key"] == cache_key
    assert captured[1][1]["prompt_cache_key"] == cache_key
    assert "max_output_tokens" not in captured[0][1]
    assert "temperature" not in captured[0][1]
    assert "prompt_cache_retention" not in captured[0][1]
    assert captured[0][1]["input"][0] == {
        "role": "developer",
        "content": [{"type": "input_text", "text": "stable system"}],
    }
    await adapter.close()


def test_codex_transport_close_is_classified_as_retryable_stream_failure() -> None:
    error = codex_adapter._request_error(
        TransportClosedError("Codex process closed stdout")
    )

    assert error.retryable is True
    assert error.stage == "stream"


class _Thread:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    async def run(self, prompt: str, **kwargs: Any) -> object:
        if self.state.get("transport_failures", 0) > 0:
            self.state["transport_failures"] -= 1
            raise TransportClosedError("Codex process closed stdout")
        self.state["prompt"] = prompt
        self.state.setdefault("prompts", []).append(prompt)
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
            state["thread_start_count"] = state.get("thread_start_count", 0) + 1
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


def test_codex_prompt_keeps_static_system_and_tools_before_dynamic_history() -> None:
    tool = {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search",
            "parameters": {"type": "object"},
        },
    }
    first = ProviderRequest(
        model="gpt-5.5",
        messages=(
            ProviderMessage(role="system", content="stable system"),
            ProviderMessage(role="system", content="turn contract"),
            ProviderMessage(role="user", content="first task"),
        ),
        tools=(tool,),
    )
    later = ProviderRequest(
        model="gpt-5.5",
        messages=(
            *first.messages,
            ProviderMessage(role="assistant", content="working"),
            ProviderMessage(role="tool", name="web_search", content="new evidence"),
        ),
        tools=(tool,),
    )

    first_prompt = codex_adapter._prompt(first)
    later_prompt = codex_adapter._prompt(later)
    common_prefix = os.path.commonprefix((first_prompt, later_prompt))

    assert first_prompt.index('"system"') < first_prompt.index('"tools"')
    assert first_prompt.index('"tools"') < first_prompt.index('"conversation"')
    assert '"name":"web_search"' in common_prefix
    assert '"content":"turn contract"' in common_prefix


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
        async for event in CodexResponsesAdapter(direct_responses=False).stream(
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
    adapter = CodexResponsesAdapter(direct_responses=False)
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
async def test_codex_oauth_reuses_run_thread_with_only_incremental_context(
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
    adapter = CodexResponsesAdapter(direct_responses=False)
    base_messages = (
        ProviderMessage(role="system", content="stable system"),
        ProviderMessage(role="user", content="inspect BF-01"),
    )
    metadata = {
        "prompt_cache_key": "lumina:user:v2:opaque",
        "codex_run_thread_id": "run-1",
    }
    first = ProviderRequest(
        model="gpt-5.5",
        messages=base_messages,
        metadata=metadata,
    )

    assert [event.type async for event in adapter.stream(first)][-1] == "completed"
    state["response"] = '{"kind":"final","text":"done","tool_calls":[]}'
    second = ProviderRequest(
        model="gpt-5.5",
        messages=(
            *base_messages,
            ProviderMessage(
                role="assistant",
                tool_calls=(
                    {
                        "id": "call_1",
                        "name": "lookup_asset",
                        "arguments_json": '{"asset":"BF-01"}',
                    },
                ),
            ),
            ProviderMessage(
                role="tool",
                name="lookup_asset",
                tool_call_id="call_1",
                content='{"temperature":1200}',
            ),
        ),
        metadata=metadata,
    )

    assert [event.type async for event in adapter.stream(second)][-1] == "completed"

    assert state["thread_start_count"] == 1
    assert len(state["prompts"]) == 2
    assert "conversation_delta" in state["prompts"][1]
    assert '"role":"tool"' in state["prompts"][1]
    assert '"role":"assistant"' not in state["prompts"][1]
    assert "static_prefix" not in state["prompts"][1]
    await adapter.close()


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
    adapter = CodexResponsesAdapter(direct_responses=False)

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
async def test_codex_oauth_discards_dead_client_after_partial_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discarded: list[object] = []

    class PartialDelta:
        def __init__(self, delta: str) -> None:
            self.delta = delta

    class InterruptedTurn:
        async def stream(self):
            yield SimpleNamespace(
                payload=PartialDelta('{"kind":"final","text":"partial')
            )
            raise TransportClosedError("Codex process closed stdout")

    class InterruptedThread:
        async def turn(self, _prompt: str, **_kwargs: Any) -> InterruptedTurn:
            return InterruptedTurn()

    class InterruptedClient:
        async def thread_start(self, **_kwargs: Any) -> InterruptedThread:
            return InterruptedThread()

    client = InterruptedClient()
    adapter = CodexResponsesAdapter(direct_responses=False)

    async def ready_client():
        return client, frozenset({"gpt-5.5"}), "."

    async def discard_client(expected: object) -> None:
        discarded.append(expected)

    monkeypatch.setattr(
        codex_adapter, "AgentMessageDeltaNotification", PartialDelta
    )
    monkeypatch.setattr(adapter, "_ready_client", ready_client)
    monkeypatch.setattr(adapter, "_discard_client", discard_client)

    events = []
    with pytest.raises(ProviderRequestError) as captured:
        async for event in adapter.stream(
            ProviderRequest(
                model="gpt-5.5",
                messages=(ProviderMessage(role="user", content="안녕"),),
            )
        ):
            events.append(event)

    assert [event.text for event in events] == ["partial"]
    assert captured.value.retryable is True
    assert captured.value.stage == "stream"
    assert discarded == [client]


@pytest.mark.asyncio
async def test_codex_oauth_discard_tolerates_dead_process_close_error() -> None:
    class DeadClient:
        async def close(self) -> None:
            raise OSError(22, "Invalid argument")

    class Workspace:
        cleaned = False

        def cleanup(self) -> None:
            self.cleaned = True

    client = DeadClient()
    workspace = Workspace()
    adapter = CodexResponsesAdapter(direct_responses=False)
    adapter._client = client  # type: ignore[assignment]
    adapter._workspace = workspace  # type: ignore[assignment]

    await adapter._discard_client(client)  # type: ignore[arg-type]

    assert adapter._client is None
    assert adapter._workspace is None
    assert workspace.cleaned is True


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
        async for event in CodexResponsesAdapter(direct_responses=False).stream(
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
    assert (
        prompt_payload["static_prefix"]["tools"][0]["function"]["name"]
        == "lookup_asset"
    )


@pytest.mark.asyncio
async def test_codex_oauth_recovers_structural_tool_argument_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {
        "response": json.dumps(
            {
                "kind": "tool_calls",
                "text": "",
                "tool_calls": [
                    {
                        "id": "call_search",
                        "name": "web_search",
                        "arguments_json": '{"query":"POSCO news"},{',
                    }
                ],
            }
        )
    }
    monkeypatch.setattr(
        "lumina.providers.codex.adapter.AsyncCodex", _fake_async_codex(state)
    )

    events = [
        event
        async for event in CodexResponsesAdapter(direct_responses=False).stream(
            ProviderRequest(
                model="gpt-5.5",
                messages=(ProviderMessage(role="user", content="검색"),),
            )
        )
    ]

    completed = next(
        event for event in events if event.type == "tool_call_completed"
    )
    assert json.loads(completed.arguments_json or "") == {"query": "POSCO news"}
    assert events[-1].stop_reason == "tool_calls"


@pytest.mark.asyncio
async def test_codex_oauth_preserves_invalid_result_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {
        "response": json.dumps(
            {
                "kind": "tool_calls",
                "text": "",
                "tool_calls": [
                    {
                        "id": "call_search",
                        "name": "web_search",
                        "arguments_json": '{"query":"POSCO"},{"query":"steel"}',
                    }
                ],
            }
        )
    }
    monkeypatch.setattr(
        "lumina.providers.codex.adapter.AsyncCodex", _fake_async_codex(state)
    )

    with pytest.raises(codex_adapter.ProviderRequestError) as captured:
        _events = [
            event
            async for event in CodexResponsesAdapter(direct_responses=False).stream(
                ProviderRequest(
                    model="gpt-5.5",
                    messages=(ProviderMessage(role="user", content="검색"),),
                )
            )
        ]

    assert captured.value.stage == "response"
    assert captured.value.status_code is None
    assert "final/tool_calls 계약" in str(captured.value)
    assert "인증을 확인" not in str(captured.value)


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
            async for event in CodexResponsesAdapter(direct_responses=False).stream(
                ProviderRequest(
                    model="gpt-5.5",
                    messages=(ProviderMessage(role="user", content="안녕"),),
                )
            )
        ]
