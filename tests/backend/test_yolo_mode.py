from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.agent.executor import local_run_executor
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Run, RunEvent, ToolApproval, ToolExecution
from lumina.providers import MockProvider, MockToolCall


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'yolo.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _wait_for_completion(client: TestClient, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 7
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}/snapshot")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        assert payload["status"] != "awaiting_approval"
        time.sleep(0.02)
    raise AssertionError(f"Run {run_id} did not finish")


def test_default_yolo_mode_executes_dangerous_tools_without_approval(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def provider(
        _provider_id: str,
        *,
        wants_artifact: bool,
        first_turn: bool,
    ) -> MockProvider:
        del wants_artifact
        if first_turn:
            return MockProvider(
                tool_call=MockToolCall(
                    name="delete_external_record",
                    arguments={"record_id": "record-1"},
                    call_id="yolo-delete-call",
                )
            )
        return MockProvider(text_chunks=("완료했습니다.",))

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(_settings(tmp_path))) as client:
        login = client.post(
            "/api/auth/login",
            json={
                "loginName": "admin",
                "loginDomain": "posco.com",
                "password": "1",
            },
        )
        assert login.status_code == 200, login.text
        headers = {"X-CSRF-Token": login.json()["csrfToken"]}
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "YOLO mode"},
        )
        started = client.post(
            f"/api/conversations/{conversation.json()['id']}/runs",
            headers={**headers, "Idempotency-Key": "default-yolo-run"},
            json={"message": {"text": "위험 작업을 실행해 주세요."}},
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run"]["runId"]
        completed = _wait_for_completion(client, run_id)
        assert completed["status"] == "completed"
        assert completed["pendingApprovals"] == []

        with SessionLocal() as db:
            run = db.get(Run, run_id)
            approvals = list(
                db.scalars(select(ToolApproval).where(ToolApproval.run_id == run_id))
            )
            approval_events = list(
                db.scalars(
                    select(RunEvent).where(
                        RunEvent.run_id == run_id,
                        RunEvent.event_type == "approval_requested",
                    )
                )
            )
            assert run is not None
            assert run.approval_mode == "yolo"
            assert run.snapshot_json["approval_mode"] == "yolo"
            assert approvals == []
            assert approval_events == []


def test_yolo_mode_does_not_persist_sensitive_tool_arguments(
    monkeypatch,
    tmp_path: Path,
) -> None:
    secret = "must-not-be-persisted"

    def provider(
        _provider_id: str,
        *,
        wants_artifact: bool,
        first_turn: bool,
    ) -> MockProvider:
        del wants_artifact
        if first_turn:
            return MockProvider(
                tool_call=MockToolCall(
                    name="send_external_message",
                    arguments={"recipient": "operator", "password": secret},
                    call_id="yolo-sensitive-call",
                )
            )
        return MockProvider(text_chunks=("완료했습니다.",))

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(_settings(tmp_path))) as client:
        login = client.post(
            "/api/auth/login",
            json={
                "loginName": "admin",
                "loginDomain": "posco.com",
                "password": "1",
            },
        )
        headers = {"X-CSRF-Token": login.json()["csrfToken"]}
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "YOLO Secret policy"},
        )
        started = client.post(
            f"/api/conversations/{conversation.json()['id']}/runs",
            headers={**headers, "Idempotency-Key": "default-yolo-sensitive-run"},
            json={"message": {"text": "Secret 인자로 전송해 주세요."}},
        )
        completed = _wait_for_completion(
            client,
            started.json()["run"]["runId"],
        )

        assert completed["toolExecutions"][0]["input"] == {}
        assert secret not in str(completed)
        with SessionLocal() as db:
            execution = db.scalar(
                select(ToolExecution).where(
                    ToolExecution.run_id == started.json()["run"]["runId"]
                )
            )
            assert execution is not None
            assert execution.error_code == "sensitive_tool_argument_forbidden"
