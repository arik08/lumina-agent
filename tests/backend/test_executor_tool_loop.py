from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from lumina.agent import executor as executor_module
from lumina.agent.executor import LocalRunExecutor, local_run_executor
from lumina.config import Settings
from lumina.main import create_app
from lumina.db import SessionLocal
from lumina.models import RunEvent, ToolExecution
from lumina.providers import (
    MockProvider,
    MockToolCall,
    ProviderMessage,
    ProviderUsage,
)
from lumina.providers.codex.adapter import _CodexToolCallStream
from lumina.tools.web import SearchInvocation, SourceEvidence, WebSearchResult


def test_codex_structured_final_text_streams_before_envelope_completion() -> None:
    expected = "첫 문장부터 보여야 합니다. 두 번째 문장도 이어집니다."
    envelope = json.dumps(
        {"kind": "final", "text": expected, "tool_calls": []},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    stream = _CodexToolCallStream()
    events = []
    for index in range(0, len(envelope), 7):
        events.extend(stream.feed(envelope[index : index + 7]))

    text_deltas = [event.text or "" for event in events if event.type == "text_delta"]
    assert len(text_deltas) > 1
    assert "".join(text_deltas) == expected


def test_progress_control_extracts_llm_authored_summary_across_chunks() -> None:
    buffer, visible, summary = executor_module._consume_progress_control("", "<pro")
    assert visible == "" and summary is None

    buffer, visible, summary = executor_module._consume_progress_control(
        buffer, "gress>관련 구현을 확인한 뒤 영향 범위를 검증하겠습니다.</progress>\n"
    )

    assert buffer is None
    assert visible == ""
    assert summary == "관련 구현을 확인한 뒤 영향 범위를 검증하겠습니다."


def test_progress_control_leaves_final_answer_text_visible() -> None:
    buffer, visible, summary = executor_module._consume_progress_control(
        "", "요청하신 작업을 완료했습니다."
    )

    assert buffer is None
    assert visible == "요청하신 작업을 완료했습니다."
    assert summary is None


def test_file_output_mode_is_a_preference_until_artifact_intent_is_explicit() -> None:
    assert executor_module._normalized_output_mode("file") == "file"
    intent_schema = executor_module._FILE_OUTPUT_INTENT_TOOL_SCHEMA["function"]
    assert intent_schema["name"] == "classify_file_output_intent"
    assert intent_schema["parameters"]["required"] == [
        "fileCreationRequested",
        "confidence",
        "reason",
    ]
    assert (
        executor_module._ARTIFACT_CREATION_REQUEST.search(
            "이 문장의 의미를 한 줄로 설명해 줘"
        )
        is None
    )
    assert (
        executor_module._ARTIFACT_CREATION_REQUEST.search(
            "앞으로 답변은 간결하게 해 줘"
        )
        is None
    )
    assert executor_module._ARTIFACT_CREATION_REQUEST.search(
        "이번 분석을 보고서 파일로 만들어 줘"
    )


def test_prompt_cache_key_tracks_static_prefix_not_dynamic_messages() -> None:
    tools = (
        executor_module._UPDATE_PLAN_TOOL_SCHEMA,
        executor_module._WEB_SEARCH_TOOL_SCHEMA,
    )
    first_messages = [
        ProviderMessage(role="system", content="stable system"),
        ProviderMessage(role="system", content="turn contract"),
        ProviderMessage(role="user", content="first task"),
    ]
    later_messages = [
        *first_messages,
        ProviderMessage(role="assistant", content="working"),
        ProviderMessage(role="tool", name="web_search", content="new evidence"),
    ]

    first_key, first_digest = executor_module._provider_prompt_cache_key(
        user_scope="lumina:user:v1:user-a",
        provider_id="codex",
        model="gpt-5.5",
        messages=first_messages,
        tools=tools,
    )
    later_key, later_digest = executor_module._provider_prompt_cache_key(
        user_scope="lumina:user:v1:user-a",
        provider_id="codex",
        model="gpt-5.5",
        messages=later_messages,
        tools=tuple(reversed(tools)),
    )

    assert first_key == later_key
    assert first_digest == later_digest
    assert first_key.startswith("lumina:user:v2:")
    assert len(first_key) == 63

    other_user_key, _ = executor_module._provider_prompt_cache_key(
        user_scope="lumina:user:v1:user-b",
        provider_id="codex",
        model="gpt-5.5",
        messages=first_messages,
        tools=tools,
    )
    other_model_key, _ = executor_module._provider_prompt_cache_key(
        user_scope="lumina:user:v1:user-a",
        provider_id="codex",
        model="gpt-5.6-sol",
        messages=first_messages,
        tools=tools,
    )
    assert other_user_key != first_key
    assert other_model_key != first_key


def test_auto_effort_preserves_explicit_choice_and_classifies_task_shape() -> None:
    assert executor_module._effective_reasoning_effort(
        "high",
        provider_id="pgpt",
        user_message="짧게 답해 줘",
        artifact_required=False,
        attachment_count=0,
        reference_count=0,
        web_research_budget=(0, 0),
    ) == "high"
    assert executor_module._effective_reasoning_effort(
        "auto",
        provider_id="pgpt",
        user_message="이 문장을 영어로 번역해 줘",
        artifact_required=False,
        attachment_count=0,
        reference_count=0,
        web_research_budget=(0, 0),
    ) == "low"
    assert executor_module._effective_reasoning_effort(
        "auto",
        provider_id="pgpt",
        user_message="런타임 장애의 근본 원인을 분석하고 수정해 줘",
        artifact_required=False,
        attachment_count=0,
        reference_count=0,
        web_research_budget=(0, 0),
    ) == "medium"
    assert executor_module._effective_reasoning_effort(
        "auto",
        provider_id="pgpt",
        user_message="도구 결과를 반영해 줘",
        artifact_required=False,
        attachment_count=0,
        reference_count=0,
        web_research_budget=(0, 0),
    ) == "low"
    assert executor_module._effective_reasoning_effort(
        "auto",
        provider_id="pgpt",
        user_message="일반적인 업무 요청의 배경과 원하는 결과를 자세히 설명합니다. " * 10,
        artifact_required=False,
        attachment_count=0,
        reference_count=0,
        web_research_budget=(0, 0),
    ) == "low"
    assert executor_module._effective_reasoning_effort(
        "auto",
        provider_id="pgpt",
        user_message="최신 자료를 조사해 줘",
        artifact_required=False,
        attachment_count=0,
        reference_count=0,
        web_research_budget=(10, 15),
    ) == "medium"
    assert executor_module._effective_reasoning_effort(
        "auto",
        provider_id="pgpt",
        user_message="첨부 내용을 확인해 줘",
        artifact_required=False,
        attachment_count=2,
        reference_count=2,
        web_research_budget=(0, 0),
    ) == "low"
    assert executor_module._effective_reasoning_effort(
        "auto",
        provider_id="pgpt",
        user_message="여러 첨부 내용을 함께 검토해 줘",
        artifact_required=False,
        attachment_count=3,
        reference_count=0,
        web_research_budget=(0, 0),
    ) == "medium"
    assert executor_module._effective_reasoning_effort(
        "auto",
        provider_id="pgpt",
        user_message="보고서를 작성해 줘",
        artifact_required=True,
        attachment_count=0,
        reference_count=0,
        web_research_budget=(10, 15),
    ) == "medium"
    assert executor_module._effective_reasoning_effort(
        "auto",
        provider_id="pgpt",
        user_message="철저하게 전수 조사해 줘",
        artifact_required=False,
        attachment_count=0,
        reference_count=0,
        web_research_budget=(20, 30),
    ) == "high"
    assert executor_module._effective_reasoning_effort(
        "auto",
        provider_id="google",
        user_message="복잡한 수학 문제를 증명해 줘",
        artifact_required=False,
        attachment_count=0,
        reference_count=0,
        web_research_budget=(0, 0),
    ) is None


def test_auto_effort_and_model_turn_metrics_are_persisted(
    monkeypatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'auto-effort-metrics.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    observed_efforts: list[str | None] = []

    class CapturingProvider(MockProvider):
        async def stream(self, request):
            observed_efforts.append(request.effort)
            async for event in super().stream(request):
                yield event

    provider = CapturingProvider(
        text_chunks=("The sentence is ready.",),
        usage=ProviderUsage(
            input_tokens=100,
            cached_input_tokens=75,
            uncached_input_tokens=25,
            output_tokens=5,
            raw={"provider": "mock"},
        ),
    )
    monkeypatch.setattr(local_run_executor, "_provider", lambda *_args, **_kwargs: provider)

    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "Auto Effort 계측"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "auto-effort-metrics-0001",
            },
            json={
                "message": {"text": "이 문장을 영어로 번역해 줘"},
                "execution": {
                    "providerId": "mock",
                    "modelKey": "mock-agent",
                    "effortId": "auto",
                },
            },
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run"]["runId"]
        snapshot = _wait_for_terminal(client, run_id)

    assert observed_efforts[0] == "low"
    assert snapshot["execution"]["effortId"] == "auto"
    metrics = snapshot["modelTurnMetrics"]
    assert metrics
    first = metrics[0]
    assert first["requestedEffort"] == "auto"
    assert first["effectiveEffort"] == "low"
    assert first["ttftMs"] is not None
    assert first["durationMs"] >= first["ttftMs"] >= 0
    assert first["cachedInputTokens"] == 75
    assert first["uncachedInputTokens"] == 25
    assert first["cacheHitRatio"] == 0.75
    with SessionLocal() as db:
        events = list(
            db.query(RunEvent).filter(
                RunEvent.run_id == run_id,
                RunEvent.event_type == "model_turn_completed",
            )
        )
    assert events
    assert events[0].payload_json["effectiveEffort"] == "low"


def test_update_plan_schema_identifies_the_report_drafting_phase() -> None:
    item_schema = executor_module._UPDATE_PLAN_TOOL_SCHEMA["function"]["parameters"][
        "properties"
    ]["plan"]["items"]

    assert "phase" in item_schema["required"]
    assert "drafting" in item_schema["properties"]["phase"]["enum"]
    assert "create_report" in item_schema["properties"]["phase"]["description"]


def test_tool_progress_fallback_does_not_expose_arguments() -> None:
    summary = executor_module._tool_progress_fallback(
        [{"name": "write_file", "arguments": '{"content":"secret"}'}]
    )

    assert "secret" not in summary
    assert "도구 작업" in summary


def test_skill_activation_can_share_the_planning_turn() -> None:
    schema = executor_module._skill_activation_tool_schema(
        {
            "extensions": [
                {
                    "extension_id": "visual-id",
                    "slug": "visual-artifact",
                    "name": "Visual Artifact",
                    "description": "HTML 시각 보고서를 제작합니다.",
                    "instructions": "Create a polished standalone HTML report.",
                }
            ],
            "prompt_references": [],
        }
    )

    assert schema is not None
    description = schema["function"]["description"]
    assert "same response as `update_plan`" in description
    assert "not with substantive tools" in description


def test_large_web_fetch_result_is_truncated_only_for_provider_context() -> None:
    result = {
        "source": {"sourceId": "src-large", "normalizedUrl": "https://example.com"},
        "text": "본문" * 20_000,
        "untrustedExternalContent": True,
    }

    content = executor_module._provider_tool_result_content("web_fetch", result)
    provider_result = json.loads(content)

    assert len(result["text"]) == 40_000
    assert len(provider_result["text"]) < len(result["text"])
    assert provider_result["source"] == result["source"]
    assert provider_result["providerContextTruncated"] is True
    assert provider_result["providerContextOriginalChars"] == 40_000
    assert provider_result["providerContextIncludedChars"] <= 15_000


def test_web_provider_context_limits_scale_with_model_window() -> None:
    assert executor_module._web_provider_context_limits(None) == (15_000, 200_000)
    assert executor_module._web_provider_context_limits({"context_window": 16_000}) == (
        9_600,
        19_200,
    )
    assert executor_module._web_provider_context_limits(
        {"context_window": 1_000_000}
    ) == (15_000, 200_000)


def test_web_tool_results_share_one_turn_context_budget() -> None:
    resolved_calls = [
        (
            {"name": "web_fetch"},
            {
                "source": {
                    "sourceId": f"src-{index}",
                    "normalizedUrl": f"https://example.com/{index}",
                },
                "text": "long evidence " * 4_000,
                "untrustedExternalContent": True,
            },
        )
        for index in range(3)
    ]

    contents = executor_module._provider_tool_result_contents(
        resolved_calls,
        capabilities={"context_window": 16_000},
    )

    assert len(contents) == 3
    assert sum(map(len, contents)) <= 19_200
    assert all(
        json.loads(content)["providerContextTruncated"] is True for content in contents
    )


def test_all_tool_results_share_one_turn_context_budget_and_keep_readback_ids() -> None:
    resolved_calls = [
        (
            {"id": f"mcp-call-{index}", "name": "mcp_read_records"},
            {"content": "large MCP evidence " * 4_000, "isError": False},
        )
        for index in range(5)
    ]

    contents = executor_module._provider_tool_result_contents(
        resolved_calls,
        capabilities={"context_window": 16_000},
        untrusted_tool_names=frozenset({"mcp_read_records"}),
    )

    assert sum(map(len, contents)) <= 19_200
    assert all("<untrusted_tool_result" in content for content in contents)
    assert all("read_tool_result" in content for content in contents)
    assert all(f"mcp-call-{index}" in contents[index] for index in range(5))


def test_individual_truncated_tool_result_exposes_recoverable_reference() -> None:
    content = executor_module._provider_tool_result_content(
        "mcp_read_records",
        {"content": "x" * 50_000},
        serialized_limit=2_000,
        tool_call_id="mcp-call-large",
    )

    payload = json.loads(content)
    assert payload["providerContextTruncated"] is True
    assert payload["toolResultReference"]["toolCallId"] == "mcp-call-large"
    assert "read_tool_result" in payload["toolResultReference"]["instruction"]


def test_web_research_uses_adaptive_guidance_with_separate_safety_limits() -> None:
    assert executor_module._web_research_budget(
        "포스코 관련 최근 3개월 언론기사 동향을 조사해줘"
    ) == (10, 15)
    assert executor_module._web_research_budget(
        "최근 철강 시장과 경쟁사 전략을 인터넷에서 조사해줘"
    ) == (10, 15)
    assert executor_module._web_research_budget(
        "포스코 관련 언론기사 동향을 심층 조사해줘"
    ) == (20, 30)
    assert executor_module._web_research_budget(
        "https://example.com/report 이 자료를 분석해줘"
    ) == (10, 15)
    assert executor_module._web_research_budget(
        "https://example.com/report 내용을 다른 출처와 비교해줘"
    ) == (10, 15)


def test_web_search_schema_distinguishes_query_calls_from_candidate_urls() -> None:
    description = executor_module._WEB_SEARCH_TOOL_SCHEMA["function"]["description"]

    assert "Each call runs one query" in description
    assert "return several candidate URLs" in description
    assert "starting guidance, not a hard limit" in description
    assert "stay within three searches" not in description


def test_web_budget_skips_overlapping_duplicate_and_excess_calls(monkeypatch) -> None:
    executor = LocalRunExecutor()
    monkeypatch.setattr(
        executor,
        "_web_attempt_state",
        lambda _run_id: (
            {"web_search": 0, "web_fetch": 0},
            {"web_search": set(), "web_fetch": set()},
        ),
    )
    calls = [
        {
            "name": "web_search",
            "arguments": json.dumps({"query": query}),
        }
        for query in (
            "POSCO steel market news",
            "news market POSCO steel",
            "POSCO tariffs",
            "POSCO lithium",
            "POSCO labor",
        )
    ]

    executor._apply_web_call_budget(
        "run-budget",
        calls,
        search_limit=3,
        fetch_limit=5,
    )

    assert calls[0].get("blocked_error") is None
    assert calls[1]["blocked_error"] == "web_duplicate_request"
    assert calls[2].get("blocked_error") is None
    assert calls[3].get("blocked_error") is None
    assert calls[4]["blocked_error"] == "web_research_safety_limit_reached"


def test_direct_url_run_keeps_search_and_fetch_tools(
    monkeypatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'direct-url-tools.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    requests = []

    class RecordingProvider(MockProvider):
        async def stream(self, request):
            requests.append(request)
            async for event in super().stream(request):
                yield event

    monkeypatch.setattr(
        local_run_executor,
        "_provider",
        lambda *_args, **_kwargs: RecordingProvider(text_chunks=("분석했습니다.",)),
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "직접 URL 분석"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "direct-url-tools-0001",
            },
            json={"message": {"text": "https://example.com/report 분석해줘"}},
        )
        assert started.status_code == 202, started.text
        snapshot = _wait_for_terminal(client, started.json()["run"]["runId"])

    assert snapshot["status"] == "completed"
    tool_names = {
        schema["function"]["name"]
        for schema in requests[0].tools
        if isinstance(schema.get("function"), dict)
    }
    assert {"web_search", "web_fetch"} <= tool_names


def test_web_fetch_signature_ignores_fragment_and_tracking_parameters() -> None:
    first = executor_module._web_call_signature(
        "web_fetch",
        {"url": "https://Example.com/report/?id=7&utm_source=news#summary"},
    )
    second = executor_module._web_call_signature(
        "web_fetch",
        {"url": "https://example.com/report?id=7"},
    )

    assert first == second


def test_write_file_progress_counts_streamed_tokens_and_lines() -> None:
    streamed = executor_module._write_file_tool_progress(
        {
            "__lumina_stream_tokens": 321,
            "__lumina_stream_lines": 27,
        }
    )
    completed = executor_module._write_file_tool_progress(
        {"content": "first line\nsecond line"}
    )

    assert streamed == {"tokens": 321, "lines": 27}
    assert completed is not None
    assert completed["tokens"] > 0
    assert completed["lines"] == 2


def test_artifact_progress_refreshes_at_100ms_with_live_model_output() -> None:
    assert executor_module._ARTIFACT_PROGRESS_INTERVAL_SECONDS == 0.1
    assert executor_module._artifact_progress_due(None, 10.0)
    assert not executor_module._artifact_progress_due(10.0, 10.099)
    assert executor_module._artifact_progress_due(10.0, 10.1)
    assert executor_module._live_model_output_tokens(3_204, 400) == 3_304


def test_streamed_write_file_name_extracts_only_the_target_name() -> None:
    arguments = '{"path":"reports\\\\quarterly_summary.html","content":"private'

    assert (
        executor_module._streamed_write_file_name(arguments) == "quarterly_summary.html"
    )
    assert executor_module._streamed_write_file_name('{"content":"private"}') is None


def test_running_tool_event_includes_web_search_query_immediately() -> None:
    tool = ToolExecution(
        id="tool-search",
        run_id="run-search",
        tool_call_id="call-search",
        tool_name="web_search",
        validated_input_json={"query": "POSCO labor union bargaining"},
        status="running",
        result_json=None,
        result_summary=None,
        artifact_id=None,
        error_message=None,
        started_at=datetime.now(UTC),
        finished_at=None,
    )

    event = executor_module._tool_event(tool)

    assert event["status"] == "running"
    assert event["input"] == {"query": "POSCO labor union bargaining"}


def test_agent_loop_persists_web_evidence_and_returns_to_model(
    monkeypatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'loop.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )

    async def fake_web_search(
        query: str, *, tool_execution_id: str, **_kwargs
    ) -> WebSearchResult:
        now = datetime.now(UTC)
        invocation = SearchInvocation(
            invocation_id="search_contract_test",
            tool_execution_id=tool_execution_id,
            query=query,
            backend="test",
            started_at=now,
        )
        source = SourceEvidence(
            source_id="src_contract_test",
            original_url="https://example.com/report",
            normalized_url="https://example.com/report",
            title="Verified report",
            domain="example.com",
            verbatim_excerpt="A concise evidence snapshot.",
            query_ids=(invocation.invocation_id,),
            tool_execution_ids=(tool_execution_id,),
            fetched_at=now,
            content_hash="a" * 64,
            evidence_kind="search_snippet",
        )
        return WebSearchResult(invocation=invocation, sources=(source,))

    def fake_provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        del wants_artifact
        if first_turn:
            return MockProvider(
                text_chunks=(
                    "<progress>최신 자료를 검색하고 출처가 분명한 근거를 선별하겠습니다.</progress>\n",
                ),
                tool_call=MockToolCall(
                    name="web_search",
                    arguments={"query": "설비 예방 정비 최신 동향", "result_limit": 3},
                    call_id="call_web_search",
                ),
            )
        return MockProvider(text_chunks=("확인한 출처를 바탕으로 답변했습니다.",))

    monkeypatch.setattr(executor_module, "web_search", fake_web_search)
    monkeypatch.setattr(local_run_executor, "_provider", fake_provider)

    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "web tool loop"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "web-loop-contract-0001",
            },
            json={
                "message": {
                    "text": "최신 동향을 확인해 주세요.",
                    "attachmentIds": [],
                    "promptReferences": [],
                },
                "execution": {
                    "providerId": "mock",
                    "modelKey": "mock-agent",
                    "effortId": "medium",
                },
            },
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run"]["runId"]
        snapshot = _wait_for_terminal(client, run_id)

        assert snapshot["status"] == "completed"
        assert [item["toolName"] for item in snapshot["toolExecutions"]] == [
            "web_search"
        ]
        assert (
            snapshot["toolExecutions"][0]["result"]["sources"][0]["sourceId"]
            == "src_contract_test"
        )
        assert [activity["type"] for activity in snapshot["activities"]] == [
            "progress_summary",
            "progress_summary",
            "tool",
        ]
        assert snapshot["activities"][1]["text"] == (
            "최신 자료를 검색하고 출처가 분명한 근거를 선별하겠습니다."
        )
        assert [activity["sequence"] for activity in snapshot["activities"]] == sorted(
            activity["sequence"] for activity in snapshot["activities"]
        )
        assert snapshot["activities"][2]["execution"]["status"] == "completed"
        assert (
            snapshot["plan"]["steps"][1]["label"]
            == "관련 자료를 탐색하고 근거를 수집합니다"
        )

        turn_sets = client.get(
            f"/api/conversations/{conversation['id']}/turn-sets"
        ).json()["turnSets"]
        assistant = [
            message
            for message in turn_sets[-1]["messages"]
            if message["role"] == "assistant"
        ][0]
        assert assistant["metadata"]["sources"][0]["normalizedUrl"] == (
            "https://example.com/report"
        )
        assert assistant["metadata"]["searchInvocations"][0]["query"] == (
            "설비 예방 정비 최신 동향"
        )


def test_file_mode_is_a_general_delivery_preference_not_a_file_command(
    monkeypatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'memory-output-mode.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    requests = []

    class RecordingProvider(MockProvider):
        async def stream(self, request):
            requests.append(request)
            async for event in super().stream(request):
                yield event

    def provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        assert wants_artifact is False
        if first_turn:
            return RecordingProvider(
                tool_call=MockToolCall(
                    name="classify_file_output_intent",
                    arguments={
                        "fileCreationRequested": False,
                        "confidence": 0.98,
                        "reason": "일반적인 설명 또는 기억 확인 질문입니다.",
                    },
                    call_id="call_file_output_intent",
                )
            )
        return RecordingProvider(text_chunks=("기억했습니다.",))

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        snapshots = []
        for index, message_text in enumerate(
            ("이 문장의 의미를 한 줄로 설명해 줘", "앞으로 답변은 간결하게 해 줘"),
            start=1,
        ):
            conversation = client.post(
                "/api/conversations",
                headers={"X-CSRF-Token": csrf},
                json={"projectId": project_id, "title": f"Memory 출력 모드 {index}"},
            ).json()
            started = client.post(
                f"/api/conversations/{conversation['id']}/runs",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": f"memory-output-mode-{index:04d}",
                },
                json={
                    "message": {
                        "text": message_text,
                        "outputMode": "file",
                    }
                },
            )
            assert started.status_code == 202, started.text
            snapshots.append(_wait_for_terminal(client, started.json()["run"]["runId"]))

    assert all(snapshot["status"] == "completed" for snapshot in snapshots)
    assert all(
        snapshot["outputIntent"]
        == {
            "fileCreationRequested": False,
            "confidence": 0.98,
            "reason": "일반적인 설명 또는 기억 확인 질문입니다.",
        }
        for snapshot in snapshots
    )
    assert all(snapshot["artifacts"] == [] for snapshot in snapshots)
    assert all(snapshot["toolExecutions"] == [] for snapshot in snapshots)
    assert len(requests) == 4
    assert {
        request.metadata["prompt_cache_key"] for request in requests
    } == {requests[0].metadata["prompt_cache_key"]}
    assert requests[0].metadata["prompt_cache_key"].startswith("lumina:user:v2:")
    run_thread_ids = [request.metadata["codex_run_thread_id"] for request in requests]
    assert run_thread_ids[0] == run_thread_ids[1]
    assert run_thread_ids[2] == run_thread_ids[3]
    assert run_thread_ids[0] != run_thread_ids[2]
    first_tool_names = None
    for request in requests:
        tool_names = {
            schema["function"]["name"]
            for schema in request.tools
            if isinstance(schema.get("function"), dict)
        }
        assert "create_report" in tool_names
        assert "write_file" in tool_names
        assert "classify_file_output_intent" in tool_names
        if first_tool_names is None:
            first_tool_names = tool_names
        else:
            assert tool_names == first_tool_names
        system_text = "\n".join(
            str(message.content)
            for message in request.messages
            if message.role == "system"
        )
        assert "Output mode: File preference." in system_text
        assert "delivery preference, not proof" in system_text
        assert "Never infer file intent solely" in system_text
        assert "File intent JSON contract" in system_text
        assert "Artifact opportunity contract" in system_text
        assert "Do not call `create_report` or `write_file`" in system_text
        assert "Memory capture contract" in system_text
        assert (
            "Artifact contract: The user requested a reusable file." not in system_text
        )


def test_chat_mode_never_exposes_or_executes_artifact_tools(
    monkeypatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'chat-only-output.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    requests = []
    provider_turn = 0

    class RecordingProvider(MockProvider):
        async def stream(self, request):
            requests.append(request)
            async for event in super().stream(request):
                yield event

    def provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        nonlocal provider_turn
        del wants_artifact, first_turn
        provider_turn += 1
        if provider_turn == 1:
            return RecordingProvider(
                tool_call=MockToolCall(
                    name="create_report",
                    arguments={
                        "format": "docx",
                        "title": "주간 업무 보고서",
                        "executive_summary": "주간 업무를 요약했습니다.",
                        "key_metrics": [],
                        "sections": [],
                        "action_items": [],
                    },
                    call_id="call_forbidden_chat_report",
                )
            )
        return RecordingProvider(
            text_chunks=("주간 업무 보고서 내용을 채팅 응답으로 작성했습니다.",)
        )

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "채팅 전용 보고서"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "chat-only-output-0001",
            },
            json={
                "message": {
                    "text": "이번 주 업무 보고서 써줘",
                    "outputMode": "chat",
                }
            },
        )
        assert started.status_code == 202, started.text
        snapshot = _wait_for_terminal(client, started.json()["run"]["runId"])

    assert snapshot["status"] == "completed"
    assert provider_turn == 2
    assert snapshot["artifacts"] == []
    assert snapshot["toolExecutions"] == []
    assert len(requests) == 2
    for request in requests:
        tool_names = {
            schema["function"]["name"]
            for schema in request.tools
            if isinstance(schema.get("function"), dict)
        }
        assert "create_report" not in tool_names
        assert "write_file" not in tool_names
    system_text = "\n".join(
        str(message.content)
        for message in requests[0].messages
        if message.role == "system"
    )
    assert "Output mode: Chat." in system_text
    assert "Never call `create_report` or `write_file`" in system_text


def test_final_answer_captures_memory_inline_without_a_second_model_call(
    monkeypatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'inline-memory.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    requests = []
    envelope = json.dumps(
        {
            "candidates": [
                {
                    "category": "recurring_rule",
                    "fact": "사용자는 주말마다 등산합니다.",
                    "confidence": 0.95,
                    "conflictKey": "weekend_activity",
                }
            ]
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    class RecordingProvider(MockProvider):
        async def stream(self, request):
            requests.append(request)
            async for event in super().stream(request):
                yield event

    def provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        assert wants_artifact is False
        assert first_turn is True
        return RecordingProvider(
            text_chunks=(
                "기억했습니다.\n<lum",
                f"ina_memory>{envelope}</lumina_",
                "memory>",
            )
        )

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "Inline Memory"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "inline-memory-0001",
            },
            json={"message": {"text": "저는 주말마다 등산을 합니다."}},
        )
        assert started.status_code == 202, started.text
        snapshot = _wait_for_terminal(client, started.json()["run"]["runId"])
        memories = client.get("/api/memories").json()

    assert snapshot["status"] == "completed"
    assert snapshot["assistantDraft"]["text"] == "기억했습니다.\n"
    assert len(requests) == 1
    assert [memory["displayText"] for memory in memories] == [
        "사용자는 주말마다 등산합니다."
    ]
    assert memories[0]["extractorVersion"] == "llm-inline-v1"


def test_file_mode_accepts_model_selected_artifact_without_explicit_file_words(
    monkeypatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'file-preference.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    provider_turn = 0

    def provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        nonlocal provider_turn
        del first_turn
        provider_turn += 1
        if provider_turn == 1:
            return MockProvider(
                tool_call=MockToolCall(
                    name="classify_file_output_intent",
                    arguments={
                        "fileCreationRequested": True,
                        "confidence": 0.91,
                        "reason": "분석 결과를 재사용 가능한 파일로 제공하는 요청입니다.",
                    },
                    call_id="call_file_output_intent",
                )
            )
        if provider_turn == 2:
            assert wants_artifact is True
            return MockProvider(
                tool_call=MockToolCall(
                    name="create_report",
                    arguments={
                        "format": "html",
                        "title": "분기 실적 분석",
                        "executive_summary": "분기 실적의 핵심 흐름을 분석했습니다.",
                        "key_metrics": [],
                        "sections": [
                            {
                                "heading": "분석 결과",
                                "body": "파일 모드 선호를 반영해 재사용 가능한 결과로 정리했습니다.",
                                "bullets": [],
                            }
                        ],
                        "action_items": [],
                    },
                    call_id="call_file_preference_report",
                )
            )
        return MockProvider(text_chunks=("분기 실적 분석 파일을 만들었습니다.",))

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "파일 선호 판단"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "file-preference-0001",
            },
            json={
                "message": {
                    "text": "이번 분기 실적을 분석해줘",
                    "outputMode": "file",
                }
            },
        )
        assert started.status_code == 202, started.text
        snapshot = _wait_for_terminal(client, started.json()["run"]["runId"])

    assert snapshot["status"] == "completed"
    assert snapshot["outputIntent"]["fileCreationRequested"] is True
    assert provider_turn == 3
    assert [tool["toolName"] for tool in snapshot["toolExecutions"]] == [
        "create_report"
    ]
    assert len(snapshot["artifacts"]) == 1


def test_report_request_recovers_when_model_tries_to_finish_without_artifact(
    monkeypatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'report-gate.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    provider_turn = 0
    observed_system_prompts: list[str] = []
    observed_stable_prefixes: list[str] = []
    report_stream_resumed_at: list[datetime] = []

    class DelayedReportProvider(MockProvider):
        async def stream(self, request):
            async for event in super().stream(request):
                yield event
                if event.type == "tool_call_started":
                    report_stream_resumed_at.append(datetime.now(UTC))
                    await asyncio.sleep(0.05)

    def provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        nonlocal provider_turn
        del first_turn
        assert wants_artifact is True
        provider_turn += 1
        if provider_turn == 1:
            return MockProvider(text_chunks=("조사 결과를 정리했습니다.",))
        if provider_turn > 2:
            return MockProvider(text_chunks=("HTML 보고서를 생성했습니다.",))
        return DelayedReportProvider(
            text_chunks=("HTML 보고서를 생성하겠습니다.",),
            tool_call=MockToolCall(
                name="create_report",
                arguments={
                    "format": "html",
                    "title": "시장 동향",
                    "executive_summary": "핵심 동향을 요약했습니다.",
                    "key_metrics": [],
                    "sections": [
                        {
                            "heading": "주요 결과",
                            "body": "검증된 자료를 바탕으로 정리한 결과입니다.",
                            "bullets": [],
                        }
                    ],
                    "action_items": [],
                },
                call_id="call_recovered_report",
            ),
        )

    original_conversation_messages = local_run_executor._conversation_messages

    def capture_messages(*args, **kwargs):
        messages = original_conversation_messages(*args, **kwargs)
        observed_stable_prefixes.append(str(messages[0].content))
        observed_system_prompts.append(
            "\n\n".join(
                str(message.content)
                for message in messages
                if message.role == "system" and message.content
            )
        )
        return messages

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    monkeypatch.setattr(local_run_executor, "_conversation_messages", capture_messages)
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "보고서 완료 조건"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "report-completion-gate-0001",
            },
            json={"message": {"text": "포스코에 간단히 설명해서 md로 파일 만들어"}},
        )
        assert started.status_code == 202, started.text
        snapshot = _wait_for_terminal(client, started.json()["run"]["runId"])

    assert snapshot["status"] == "completed"
    assert provider_turn >= 2
    assert [tool["toolName"] for tool in snapshot["toolExecutions"]] == [
        "create_report"
    ]
    report_tool_started_at = datetime.fromisoformat(
        snapshot["toolExecutions"][0]["startedAt"].replace("Z", "+00:00")
    )
    assert report_stream_resumed_at
    assert report_tool_started_at <= report_stream_resumed_at[0]
    assert len(snapshot["artifacts"]) == 1
    assert "must call `create_report`" in observed_system_prompts[0]
    assert "`html_source` argument" in observed_system_prompts[0]
    assert (
        "Lumina renders it and supplies the expand/zoom viewer"
        in observed_system_prompts[0]
    )
    assert "around 10,000-12,000 tokens" in observed_system_prompts[0]
    assert "Never expose internal Artifact IDs" in observed_system_prompts[0]
    assert (
        "refer to it only by its user-visible display name"
        in observed_system_prompts[0]
    )
    assert (
        "without internal IDs or raw tool-result fields" in observed_system_prompts[0]
    )
    assert "must call `create_report`" not in observed_stable_prefixes[0]


def test_executable_html_write_file_satisfies_artifact_completion_gate(
    monkeypatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'html-write-gate.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    provider_turn = 0

    def provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        nonlocal provider_turn
        del first_turn
        assert wants_artifact is True
        provider_turn += 1
        if provider_turn > 1:
            return MockProvider(text_chunks=("실행 가능한 HTML 게임을 만들었습니다.",))
        return MockProvider(
            text_chunks=("HTML 게임 파일을 만들겠습니다.",),
            tool_call=MockToolCall(
                name="write_file",
                arguments={
                    "path": "game.html",
                    "content": (
                        "<!doctype html><html><body><p id='status'>대기</p>"
                        "<script>document.getElementById('status').textContent='실행';"
                        "</script></body></html>"
                    ),
                },
                call_id="call_html_game",
            ),
        )

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "HTML 게임 완료 조건"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "html-write-completion-gate-0001",
            },
            json={"message": {"text": "자바스크립트가 실행되는 HTML 게임을 만들어줘"}},
        )
        assert started.status_code == 202, started.text
        snapshot = _wait_for_terminal(client, started.json()["run"]["runId"])

    assert snapshot["status"] == "completed"
    assert provider_turn == 2
    assert [tool["toolName"] for tool in snapshot["toolExecutions"]] == ["write_file"]
    assert len(snapshot["artifacts"]) == 1
    assert snapshot["artifacts"][0]["displayName"] == "game.html"


def test_independent_tool_calls_run_in_parallel_and_persist_subtasks(
    monkeypatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'parallel-tools.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
        tool_concurrency_limit=2,
    )
    active = 0
    max_active = 0

    async def delayed_search(
        query: str, *, tool_execution_id: str, **_kwargs
    ) -> WebSearchResult:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.08)
        active -= 1
        now = datetime.now(UTC)
        invocation = SearchInvocation(
            invocation_id=f"search-{tool_execution_id}",
            tool_execution_id=tool_execution_id,
            query=query,
            backend="test",
            started_at=now,
        )
        source = SourceEvidence(
            source_id=f"source-{tool_execution_id}",
            original_url=f"https://example.com/{tool_execution_id}",
            normalized_url=f"https://example.com/{tool_execution_id}",
            title=query,
            domain="example.com",
            verbatim_excerpt="parallel evidence",
            query_ids=(invocation.invocation_id,),
            tool_execution_ids=(tool_execution_id,),
            fetched_at=now,
            content_hash="b" * 64,
            evidence_kind="search_snippet",
        )
        return WebSearchResult(invocation=invocation, sources=(source,))

    def provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        del wants_artifact
        if first_turn:
            return MockProvider(
                text_chunks=("두 근거를 확인합니다.",),
                tool_calls=(
                    MockToolCall(
                        name="web_search",
                        arguments={"query": "근거 A"},
                        call_id="parallel-a",
                    ),
                    MockToolCall(
                        name="web_search",
                        arguments={"query": "근거 B"},
                        call_id="parallel-b",
                    ),
                ),
            )
        return MockProvider(text_chunks=("병렬 근거 확인을 완료했습니다.[1][2]",))

    monkeypatch.setattr(executor_module, "web_search", delayed_search)
    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "병렬 Subtask"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "parallel-tools-contract-0001",
            },
            json={"message": {"text": "두 근거를 동시에 확인해 주세요."}},
        )
        assert started.status_code == 202, started.text
        snapshot = _wait_for_terminal(client, started.json()["run"]["runId"])

        assert snapshot["status"] == "completed"
        assert max_active == 2
        tools_step = next(
            step for step in snapshot["plan"]["steps"] if step["key"] == "tools"
        )
        assert [subtask["status"] for subtask in tools_step["subtasks"]] == [
            "completed",
            "completed",
        ]
        assert [subtask["toolCallId"] for subtask in tools_step["subtasks"]] == [
            "parallel-a",
            "parallel-b",
        ]


def test_update_plan_tool_publishes_meaningful_plan_without_tool_activity(
    monkeypatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'work-plan-loop.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    provider_turn = 0
    steps = [
        "CodeGraph에서 실행 이벤트와 화면 렌더링 경로를 확인합니다",
        "모델 계획 이벤트를 Run snapshot과 SSE에 연결합니다",
        "브라우저에서 단계 상태와 오류 여부를 검증합니다",
    ]

    def provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        nonlocal provider_turn
        del wants_artifact, first_turn
        provider_turn += 1
        if provider_turn == 1:
            statuses = ["in_progress", "pending", "pending"]
        elif provider_turn == 2:
            statuses = ["completed", "completed", "completed"]
        else:
            return MockProvider(text_chunks=("계획한 검증까지 완료했습니다.",))
        return MockProvider(
            tool_call=MockToolCall(
                name="update_plan",
                arguments={
                    "plan": [
                        {"step": step, "status": status}
                        for step, status in zip(steps, statuses, strict=True)
                    ]
                },
                call_id=f"work-plan-{provider_turn}",
            )
        )

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "의미 있는 업무 계획"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "work-plan-tool-contract-0001",
            },
            json={"message": {"text": "계획을 세워 구현하고 검증해 주세요."}},
        )
        assert started.status_code == 202, started.text
        snapshot = _wait_for_terminal(client, started.json()["run"]["runId"])

        assert snapshot["status"] == "completed"
        assert [item["step"] for item in snapshot["workPlan"]] == steps
        assert {item["status"] for item in snapshot["workPlan"]} == {"completed"}
        assert snapshot["toolExecutions"] == []


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
    deadline = time.monotonic() + 5
    payload: dict[str, object] = {}
    while time.monotonic() < deadline:
        payload = client.get(f"/api/runs/{run_id}/snapshot").json()
        if payload["status"] in {
            "completed",
            "failed",
            "cancelled",
            "limit_reached",
            "interrupted",
        }:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"Run did not reach a terminal state: {payload}")
