from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.agent.executor import local_run_executor
from lumina.auth import create_user
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import (
    Organization,
    ProjectMembership,
    Run,
    RunEvent,
    ToolApproval,
    ToolExecution,
    User,
)
from lumina.providers import MockProvider, MockToolCall
from lumina.runs.approvals import classify_tool_risk


def _settings(tmp_path: Path, name: str) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
        user_concurrency_limit=1,
        server_concurrency_limit=1,
    )


def test_mcp_preview_and_connection_checks_are_external_reads() -> None:
    for tool_name in ("preview_trade_data", "check_connection"):
        risk = classify_tool_risk(
            f"mcp__comtrade__{tool_name}__digest",
            approval_mode="on_risk",
            mcp_original_name=tool_name,
        )
        assert risk.effect == "external_read"
        assert risk.risk_level == "low"
        assert risk.approval_required is False


def _login(
    client: TestClient,
    login_name: str = "admin",
    password: str = "1",
) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": login_name,
            "loginDomain": "posco.com",
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def _start_run(
    client: TestClient,
    headers: dict[str, str],
    *,
    suffix: str,
) -> tuple[str, str]:
    settings = client.get("/api/admin/run-safety")
    assert settings.status_code == 200, settings.text
    disabled_yolo = client.patch(
        "/api/admin/run-safety",
        headers=headers,
        json={**settings.json(), "yoloMode": False},
    )
    assert disabled_yolo.status_code == 200, disabled_yolo.text
    project_id = client.get("/api/projects").json()[0]["id"]
    conversation = client.post(
        "/api/conversations",
        headers=headers,
        json={"projectId": project_id, "title": f"Tool 승인 {suffix}"},
    )
    assert conversation.status_code == 201, conversation.text
    started = client.post(
        f"/api/conversations/{conversation.json()['id']}/runs",
        headers={
            **headers,
            "Idempotency-Key": f"tool-approval-start-{suffix}",
        },
        json={"message": {"text": "위험 작업을 검토해 주세요."}},
    )
    assert started.status_code == 202, started.text
    return started.json()["run"]["runId"], project_id


def _wait_for_status(
    client: TestClient,
    run_id: str,
    expected: set[str],
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


def _dangerous_provider(
    _provider_id: str,
    *,
    wants_artifact: bool,
    first_turn: bool,
) -> MockProvider:
    del wants_artifact
    if first_turn:
        return MockProvider(
            text_chunks=("외부 레코드 삭제를 준비합니다.",),
            tool_call=MockToolCall(
                name="delete_external_record",
                arguments={
                    "record_id": "record-value-not-for-approval",
                    "scope": "plant",
                },
                call_id="dangerous-delete-call",
            ),
        )
    return MockProvider(text_chunks=("승인 결과를 반영해 안전하게 마무리했습니다.",))


def test_dangerous_tool_approval_is_durable_authorized_and_idempotent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(local_run_executor, "_provider", _dangerous_provider)
    with TestClient(create_app(_settings(tmp_path, "approve.db"))) as client:
        admin_headers = _login(client)
        run_id, project_id = _start_run(client, admin_headers, suffix="approve")
        waiting = _wait_for_status(client, run_id, {"awaiting_approval"})

        assert len(waiting["pendingApprovals"]) == 1
        approval = waiting["pendingApprovals"][0]
        assert approval["toolName"] == "delete_external_record"
        assert approval["effect"] == "destructive"
        assert approval["summary"] == {
            "argumentCount": 2,
            "argumentFields": ["record_id", "scope"],
            "sensitiveFieldCount": 0,
        }
        assert "record-value-not-for-approval" not in json.dumps(
            waiting, ensure_ascii=False, default=str
        )

        _wait_for_detached_wait(run_id)
        capacity_run_id, _capacity_project_id = _start_run(
            client, admin_headers, suffix="capacity"
        )
        _wait_for_status(client, capacity_run_id, {"awaiting_approval"})

        with SessionLocal() as db:
            organization = db.scalar(select(Organization))
            admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert organization is not None and admin is not None
            member = create_user(
                db,
                login_name="approval-member",
                password="member-password",
                organization_id=organization.id,
                created_by_user_id=admin.id,
            )
            db.add(
                ProjectMembership(
                    project_id=project_id,
                    user_id=member.id,
                    role="member",
                    status="active",
                    created_by_user_id=admin.id,
                )
            )
            db.commit()

        member_headers = _login(client, "approval-member", "member-password")
        forbidden = client.post(
            f"/api/runs/{run_id}/actions",
            headers={
                **member_headers,
                "Idempotency-Key": "tool-approval-member-forbidden",
            },
            json={"type": "approve", "approvalId": approval["id"]},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "approval_forbidden"

        admin_headers = _login(client)
        action_headers = {
            **admin_headers,
            "Idempotency-Key": "tool-approval-owner-approve",
        }
        approved = client.post(
            f"/api/runs/{run_id}/actions",
            headers=action_headers,
            json={"type": "approve", "approvalId": approval["id"]},
        )
        assert approved.status_code == 200, approved.text
        duplicate = client.post(
            f"/api/runs/{run_id}/actions",
            headers=action_headers,
            json={"type": "approve", "approvalId": approval["id"]},
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["command"]["id"] == approved.json()["command"]["id"]

        completed = _wait_for_status(client, run_id, {"completed"})
        assert completed["pendingApprovals"] == []
        assert completed["toolExecutions"][0]["toolName"] == "delete_external_record"

        with SessionLocal() as db:
            stored = db.get(ToolApproval, approval["id"])
            execution = db.scalar(
                select(ToolExecution).where(ToolExecution.run_id == run_id)
            )
            approval_events = list(
                db.scalars(
                    select(RunEvent).where(
                        RunEvent.run_id == run_id,
                        RunEvent.event_type.in_(
                            ["approval_requested", "approval_resolved"]
                        ),
                    )
                )
            )
            assert stored is not None and stored.status == "approved"
            assert execution is not None and execution.error_code == "unknown_tool"
            assert {event.event_type for event in approval_events} == {
                "approval_requested",
                "approval_resolved",
            }
            assert "record-value-not-for-approval" not in json.dumps(
                [event.payload_json for event in approval_events],
                ensure_ascii=False,
                default=str,
            )


def test_rejected_tool_returns_policy_result_without_dispatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(local_run_executor, "_provider", _dangerous_provider)
    with TestClient(create_app(_settings(tmp_path, "reject.db"))) as client:
        headers = _login(client)
        run_id, _project_id = _start_run(client, headers, suffix="reject")
        waiting = _wait_for_status(client, run_id, {"awaiting_approval"})
        approval_id = waiting["pendingApprovals"][0]["id"]

        rejected = client.post(
            f"/api/runs/{run_id}/actions",
            headers={
                **headers,
                "Idempotency-Key": "tool-approval-owner-reject",
            },
            json={"type": "reject", "approvalId": approval_id},
        )
        assert rejected.status_code == 200, rejected.text
        completed = _wait_for_status(client, run_id, {"completed"})
        assert completed["pendingApprovals"] == []

        with SessionLocal() as db:
            approval = db.get(ToolApproval, approval_id)
            execution = db.scalar(
                select(ToolExecution).where(ToolExecution.run_id == run_id)
            )
            assert approval is not None and approval.status == "rejected"
            assert execution is not None
            assert execution.error_code == "tool_approval_rejected"
            assert execution.error_message == "사용자가 위험 작업 승인을 거부했습니다."


def test_sensitive_dangerous_arguments_are_blocked_without_persistence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    secret = "credential-that-must-not-be-stored"

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
                    call_id="sensitive-send-call",
                )
            )
        return MockProvider(text_chunks=("Secret binding이 필요하다고 안내했습니다.",))

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(_settings(tmp_path, "sensitive.db"))) as client:
        headers = _login(client)
        run_id, _project_id = _start_run(client, headers, suffix="sensitive")
        completed = _wait_for_status(client, run_id, {"completed"})

        assert completed["pendingApprovals"] == []
        assert completed["toolExecutions"][0]["input"] == {}
        with SessionLocal() as db:
            approvals = list(
                db.scalars(select(ToolApproval).where(ToolApproval.run_id == run_id))
            )
            execution = db.scalar(
                select(ToolExecution).where(ToolExecution.run_id == run_id)
            )
            events = list(db.scalars(select(RunEvent).where(RunEvent.run_id == run_id)))
            assert approvals == []
            assert execution is not None
            assert execution.error_code == "sensitive_tool_argument_forbidden"
            assert secret not in json.dumps(
                {
                    "snapshot": completed,
                    "input": execution.validated_input_json,
                    "events": [event.payload_json for event in events],
                },
                ensure_ascii=False,
                default=str,
            )
