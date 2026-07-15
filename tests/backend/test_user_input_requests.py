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
    )


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "admin",
            "loginDomain": "posco.com",
            "password": "1",
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
        assert len(waiting["inputRequests"]) == 1
        request = waiting["inputRequests"][0]
        assert request["status"] == "pending"
        assert len(request["questions"]) == 2

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
