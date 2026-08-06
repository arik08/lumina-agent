from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.agent.executor import local_run_executor
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Run, RunEvent, UserSetting
from lumina.providers import MockProvider, MockToolCall


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'clarification.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
        user_concurrency_limit=1,
        server_concurrency_limit=1,
    )


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "admin",
            "loginDomain": "posco.com",
            "password": "1111",
        },
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def _wait_for_status(
    client: TestClient, run_id: str, expected: set[str]
) -> dict[str, object]:
    deadline = time.monotonic() + 7
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}/snapshot")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in expected:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"Run {run_id} did not reach {sorted(expected)}")


def _wait_for_detached_wait(run_id: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            if (
                run is not None
                and run.worker_id is None
                and run_id not in local_run_executor._tasks
            ):
                return
        time.sleep(0.02)
    raise AssertionError(f"Run {run_id} did not release its waiting executor task")


def _clarifying_provider(
    _provider_id: str,
    *,
    wants_artifact: bool,
    first_turn: bool,
) -> MockProvider:
    del wants_artifact
    if first_turn:
        return MockProvider(
            tool_call=MockToolCall(
                name="request_user_input",
                call_id="clarification-call",
                arguments={
                    "questions": [
                        {
                            "id": "format",
                            "prompt": "결과를 어떤 형태로 정리할까요?",
                            "options": [
                                {"id": "brief", "label": "간단히"},
                                {"id": "detail", "label": "자세히"},
                            ],
                        },
                        {
                            "id": "audience",
                            "prompt": "누가 읽을 자료인가요?",
                            "options": [
                                {"id": "team", "label": "실무팀"},
                                {"id": "leader", "label": "리더"},
                            ],
                        },
                    ]
                },
            )
        )
    return MockProvider(text_chunks=("선택한 조건에 맞춰 정리했습니다.",))


def test_account_clarification_setting_and_durable_input_resume(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(local_run_executor, "_provider", _clarifying_provider)
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        current = client.get("/api/settings/current").json()
        assert current["clarificationMode"] == "balanced"

        updated = client.patch(
            "/api/settings/current",
            headers=headers,
            json={
                "clarificationMode": "confirming",
                "expectedRevision": current["revision"],
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["clarificationMode"] == "confirming"

        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "확인 질문 테스트"},
        )
        started = client.post(
            f"/api/conversations/{conversation.json()['id']}/runs",
            headers={**headers, "Idempotency-Key": "clarification-start"},
            json={"message": {"text": "자료를 정리해 주세요."}},
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run"]["runId"]
        waiting = _wait_for_status(client, run_id, {"awaiting_input"})
        provider_messages = local_run_executor._conversation_messages(
            run_id, "역질문 여러 개를 던져 주세요."
        )
        provider_system_text = "\n".join(
            str(message.content)
            for message in provider_messages
            if message.role == "system" and message.content
        )
        assert "whenever you decide that you need to ask the person" in provider_system_text
        assert "MUST use `request_user_input`" in provider_system_text
        assert "never put questions for the person in visible answer text" in (
            provider_system_text
        )
        assert "each independent fact or decision as a separate question" in (
            provider_system_text
        )
        assert "never pack multiple facts into one prompt" in provider_system_text
        assert "every currently foreseeable high-value question in the first bundle" in (
            provider_system_text
        )
        assert "do not intentionally split known questions" in provider_system_text
        assert "repeated submit-and-wait cycles" in provider_system_text
        assert "Personalized-guidance intake" in provider_system_text
        assert "generic list of conditional 'if X, then Y' advice" in (
            provider_system_text
        )
        assert "missing user-specific facts could materially change" in (
            provider_system_text
        )
        assert "Role-play framing such as assigning you a profession" in (
            provider_system_text
        )
        assert "Do not trigger intake merely for general knowledge" in (
            provider_system_text
        )
        assert "Underspecified retrieval intake" in provider_system_text
        assert "Before using local files, enterprise search, an MCP" in (
            provider_system_text
        )
        assert "'find a document' or 'search for it' is not actionable" in (
            provider_system_text
        )
        assert "selected files, project context, or explicit filters" in (
            provider_system_text
        )
        assert len(waiting["inputRequests"]) == 1
        request = waiting["inputRequests"][0]
        assert request["status"] == "pending"
        assert len(request["questions"]) == 2

        _wait_for_detached_wait(run_id)
        capacity_conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "확인 대기 중 슬롯 검증"},
        )
        capacity_started = client.post(
            f"/api/conversations/{capacity_conversation.json()['id']}/runs",
            headers={**headers, "Idempotency-Key": "clarification-capacity-start"},
            json={"message": {"text": "별도 자료도 정리해 주세요."}},
        )
        assert capacity_started.status_code == 202, capacity_started.text
        _wait_for_status(
            client,
            capacity_started.json()["run"]["runId"],
            {"awaiting_input"},
        )

        incomplete = client.post(
            f"/api/runs/{run_id}/actions",
            headers={**headers, "Idempotency-Key": "clarification-incomplete"},
            json={
                "type": "submit_user_input",
                "inputRequestId": request["id"],
                "answers": [{"questionId": "format", "optionId": "brief"}],
            },
        )
        assert incomplete.status_code == 422
        assert incomplete.json()["code"] == "input_answers_incomplete"

        submitted = client.post(
            f"/api/runs/{run_id}/actions",
            headers={**headers, "Idempotency-Key": "clarification-submit"},
            json={
                "type": "submit_user_input",
                "inputRequestId": request["id"],
                "answers": [
                    {"questionId": "format", "optionId": "detail"},
                    {"questionId": "audience", "customText": "신입 구성원"},
                ],
            },
        )
        assert submitted.status_code == 200, submitted.text
        completed = _wait_for_status(client, run_id, {"completed"})
        assert completed["inputRequests"][0]["status"] == "submitted"
        input_activities = [
            activity
            for activity in completed["activities"]
            if activity["type"] == "input_request"
        ]
        assert len(input_activities) == 1
        assert input_activities[0]["request"]["id"] == request["id"]
        assert input_activities[0]["request"]["status"] == "submitted"

        with SessionLocal() as db:
            run = db.get(Run, run_id)
            setting = db.scalar(
                select(UserSetting).where(
                    UserSetting.key == "agent.clarification_mode"
                )
            )
            events = set(
                db.scalars(
                    select(RunEvent.event_type).where(RunEvent.run_id == run_id)
                )
            )
            assert run is not None
            assert run.snapshot_json["clarification_mode"] == "confirming"
            assert "tool_checkpoint" not in run.snapshot_json
            assert setting is not None and setting.value_json == "confirming"
            assert {
                "input_requested",
                "input_submitted",
                "input_checkpoint_consumed",
            } <= events


def test_ten_question_bundle_can_be_submitted_in_one_action(
    monkeypatch,
    tmp_path: Path,
) -> None:
    questions = [
        {
            "id": f"intake_{index}",
            "prompt": f"확인 질문 {index}",
            "options": [
                {"id": "yes", "label": "예"},
                {"id": "no", "label": "아니요"},
            ],
        }
        for index in range(1, 11)
    ]

    def ten_question_provider(
        _provider_id: str,
        *,
        wants_artifact: bool,
        first_turn: bool,
    ) -> MockProvider:
        del wants_artifact
        if first_turn:
            return MockProvider(
                tool_call=MockToolCall(
                    name="request_user_input",
                    call_id="ten-question-bundle",
                    arguments={"questions": questions},
                )
            )
        return MockProvider(text_chunks=("열 가지 답변을 반영했습니다.",))

    monkeypatch.setattr(local_run_executor, "_provider", ten_question_provider)
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "열 문항 제출 검증"},
        )
        started = client.post(
            f"/api/conversations/{conversation.json()['id']}/runs",
            headers={**headers, "Idempotency-Key": "ten-question-start"},
            json={"message": {"text": "인터뷰를 시작해 주세요."}},
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run"]["runId"]
        waiting = _wait_for_status(client, run_id, {"awaiting_input"})
        request = waiting["inputRequests"][0]
        assert len(request["questions"]) == 10

        submitted = client.post(
            f"/api/runs/{run_id}/actions",
            headers={**headers, "Idempotency-Key": "ten-question-submit"},
            json={
                "type": "submit_user_input",
                "inputRequestId": request["id"],
                "answers": [
                    {"questionId": question["id"], "optionId": "yes"}
                    for question in questions
                ],
            },
        )
        assert submitted.status_code == 200, submitted.text
        completed = _wait_for_status(client, run_id, {"completed"})
        assert completed["inputRequests"][0]["status"] == "submitted"


def test_explicit_interview_can_resume_into_a_second_question_card(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider_turn = 0

    def adaptive_interview_provider(
        _provider_id: str,
        *,
        wants_artifact: bool,
        first_turn: bool,
    ) -> MockProvider:
        nonlocal provider_turn
        del wants_artifact, first_turn
        provider_turn += 1
        if provider_turn == 1:
            return MockProvider(
                tool_call=MockToolCall(
                    name="request_user_input",
                    call_id="interview-goal",
                    arguments={
                        "questions": [
                            {
                                "id": "goal",
                                "prompt": "가장 중요한 목표는 무엇인가요?",
                                "options": [
                                    {"id": "speed", "label": "빠른 실행"},
                                    {"id": "quality", "label": "높은 완성도"},
                                ],
                            }
                        ]
                    },
                )
            )
        if provider_turn == 2:
            return MockProvider(
                tool_call=MockToolCall(
                    name="request_user_input",
                    call_id="interview-quality-bar",
                    arguments={
                        "questions": [
                            {
                                "id": "quality_bar",
                                "prompt": "완성도를 무엇으로 판단할까요?",
                                "options": [
                                    {"id": "review", "label": "검토 통과"},
                                    {"id": "test", "label": "테스트 통과"},
                                ],
                            }
                        ]
                    },
                )
            )
        return MockProvider(text_chunks=("합의한 목표와 완료 조건에 맞춰 실행했습니다.",))

    monkeypatch.setattr(local_run_executor, "_provider", adaptive_interview_provider)
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "적응형 인터뷰 테스트"},
        )
        started = client.post(
            f"/api/conversations/{conversation.json()['id']}/runs",
            headers={**headers, "Idempotency-Key": "adaptive-interview-start"},
            json={"message": {"text": "$ask-me로 계획을 구체화해 주세요."}},
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run"]["runId"]

        first_wait = _wait_for_status(client, run_id, {"awaiting_input"})
        first_request = first_wait["inputRequests"][0]
        first_submit = client.post(
            f"/api/runs/{run_id}/actions",
            headers={**headers, "Idempotency-Key": "adaptive-interview-goal"},
            json={
                "type": "submit_user_input",
                "inputRequestId": first_request["id"],
                "answers": [{"questionId": "goal", "optionId": "quality"}],
            },
        )
        assert first_submit.status_code == 200, first_submit.text

        second_wait = _wait_for_status(client, run_id, {"awaiting_input"})
        assert len(second_wait["inputRequests"]) == 2
        assert second_wait["inputRequests"][0]["status"] == "submitted"
        second_request = second_wait["inputRequests"][1]
        assert second_request["status"] == "pending"
        assert second_request["questions"][0]["id"] == "quality_bar"
        second_submit = client.post(
            f"/api/runs/{run_id}/actions",
            headers={**headers, "Idempotency-Key": "adaptive-interview-quality"},
            json={
                "type": "submit_user_input",
                "inputRequestId": second_request["id"],
                "answers": [{"questionId": "quality_bar", "optionId": "test"}],
            },
        )
        assert second_submit.status_code == 200, second_submit.text

        completed = _wait_for_status(client, run_id, {"completed"})
        assert [item["status"] for item in completed["inputRequests"]] == [
            "submitted",
            "submitted",
        ]
        input_activities = [
            activity
            for activity in completed["activities"]
            if activity["type"] == "input_request"
        ]
        assert [activity["request"]["id"] for activity in input_activities] == [
            first_request["id"],
            second_request["id"],
        ]
