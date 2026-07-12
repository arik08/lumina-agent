from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from lumina.agent import executor as executor_module
from lumina.agent.executor import local_run_executor
from lumina.config import Settings
from lumina.main import create_app
from lumina.providers import MockProvider, MockToolCall
from lumina.tools.web import SearchInvocation, SourceEvidence, WebSearchResult


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


def test_tool_progress_fallback_does_not_expose_arguments() -> None:
    summary = executor_module._tool_progress_fallback(
        [{"name": "write_file", "arguments": '{"content":"secret"}'}]
    )

    assert "secret" not in summary
    assert "도구 작업" in summary


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
                text_chunks=("<progress>최신 자료를 검색하고 출처가 분명한 근거를 선별하겠습니다.</progress>\n",),
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
        assert snapshot["plan"]["steps"][1]["label"] == "관련 자료 탐색 및 근거 수집"

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
        return MockProvider(
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
        observed_system_prompts.append(str(messages[0].content))
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
    assert len(snapshot["artifacts"]) == 1
    assert "must call `create_report`" in observed_system_prompts[0]


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
    raise AssertionError("Run did not reach a terminal state")
