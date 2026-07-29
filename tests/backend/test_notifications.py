from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lumina.api.schemas import RunCreate, RunMessageInput
from lumina.auth.service import create_user
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import (
    Artifact,
    AuditEvent,
    Conversation,
    Notification,
    Organization,
    Run,
    ToolExecution,
    User,
)
from lumina.notifications import create_run_transition_notification
from lumina.notifications import service as notification_service
from lumina.runs.service import create_run, transition_run
from lumina.runs.state import (
    AWAITING_APPROVAL,
    COMPLETED,
    FAILED,
    MODEL_STREAMING,
    PREPARING,
    TERMINAL_STATUSES,
)


def _settings(tmp_path: Path, name: str) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _login(
    client: TestClient, name: str = "admin", password: str = "1111"
) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"loginName": name, "loginDomain": "posco.com", "password": password},
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def _conversation(
    client: TestClient, csrf: dict[str, str], title: str
) -> tuple[str, str]:
    project_id = client.get("/api/projects").json()[0]["id"]
    response = client.post(
        "/api/conversations",
        headers=csrf,
        json={"projectId": project_id, "title": title},
    )
    assert response.status_code == 201, response.text
    return project_id, response.json()["id"]


def _wait_for_terminal(client: TestClient, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}/snapshot")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in TERMINAL_STATUSES:
            return payload
        time.sleep(0.03)
    raise AssertionError("Run did not reach a terminal state")


def _create_other_admin() -> None:
    with SessionLocal() as db:
        organization_id = db.scalar(
            select(Organization.id).where(Organization.slug == "posco")
        )
        assert organization_id is not None
        create_user(
            db,
            login_name="notification-other",
            password="password",
            organization_id=organization_id,
            role="admin",
        )
        db.commit()


def test_run_notification_is_persistent_idempotent_isolated_and_device_synced(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path, "run-notifications.db"))
    with TestClient(app) as first:
        csrf = _login(first)
        project_id, conversation_id = _conversation(first, csrf, "백그라운드 작업")
        secret_prompt = "보고서를 작성해 주세요. secret=NEVER-STORE-THIS"
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert user is not None
            run, _message, _created = create_run(
                db,
                user=user,
                conversation_id=conversation_id,
                payload=RunCreate(message=RunMessageInput(text=secret_prompt)),
                idempotency_key="notification-run-0001",
            )
            transition_run(db, run, PREPARING)
            transition_run(db, run, MODEL_STREAMING)
            db.add(
                ToolExecution(
                    run_id=run.id,
                    tool_call_id="notification-tool-call-0001",
                    tool_name="web_search",
                    validated_input_json={},
                    status="completed",
                )
            )
            transition_run(db, run, COMPLETED)
            db.commit()
            run_id = run.id

        listing = first.get("/api/notifications")
        assert listing.status_code == 200, listing.text
        payload = listing.json()
        assert payload["unreadCount"] == 1
        assert payload["hasMore"] is False
        notification = payload["items"][0]
        assert notification["kind"] == "run_completed"
        assert notification["readAt"] is None
        assert notification["deepLink"] == {
            "target": "conversation",
            "projectId": project_id,
            "conversationId": conversation_id,
            "runId": run_id,
        }
        assert "NEVER-STORE-THIS" not in json.dumps(payload, ensure_ascii=False)

        with SessionLocal() as db:
            run = db.get(Run, run_id)
            assert run is not None
            _row, created = create_run_transition_notification(db, run, "completed")
            assert created is False
            assert db.scalar(select(func.count(Notification.id))) == 1
            audit_payload = [
                event.metadata_json
                for event in db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "notification_created"
                    )
                )
            ]
            assert "NEVER-STORE-THIS" not in json.dumps(
                audit_payload, ensure_ascii=False
            )

        second = TestClient(app)
        try:
            second_csrf = _login(second)
            assert second.get("/api/notifications/unread-count").json() == {
                "unreadCount": 1
            }
            read = second.post(
                f"/api/notifications/{notification['id']}/read",
                headers=second_csrf,
            )
            assert read.status_code == 200, read.text
            assert read.json()["readAt"] is not None
        finally:
            second.close()
        assert first.get("/api/notifications/unread-count").json() == {"unreadCount": 0}
        deleted = first.delete(
            f"/api/notifications/{notification['id']}",
            headers=csrf,
        )
        assert deleted.status_code == 204, deleted.text
        assert first.get("/api/notifications").json()["items"] == []

        _create_other_admin()
        other = TestClient(app)
        try:
            other_csrf = _login(other, "notification-other", "password")
            assert other.get("/api/notifications").json()["items"] == []
            forbidden = other.post(
                f"/api/notifications/{notification['id']}/read",
                headers=other_csrf,
            )
            assert forbidden.status_code == 404
            assert forbidden.json()["code"] == "notification_not_found"
        finally:
            other.close()


def test_simple_chat_completion_does_not_create_notification(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, "simple-chat-notifications.db"))
    with TestClient(app) as client:
        csrf = _login(client)
        _project_id, conversation_id = _conversation(client, csrf, "단순 채팅")
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert user is not None
            run, _message, _created = create_run(
                db,
                user=user,
                conversation_id=conversation_id,
                payload=RunCreate(message=RunMessageInput(text="간단한 질문")),
                idempotency_key="notification-simple-chat-0001",
            )
            transition_run(db, run, PREPARING)
            transition_run(db, run, MODEL_STREAMING)
            transition_run(db, run, COMPLETED)
            db.commit()

        listing = client.get("/api/notifications")
        assert listing.status_code == 200, listing.text
        assert listing.json()["items"] == []
        assert listing.json()["unreadCount"] == 0


def test_deep_analysis_only_notifies_for_final_report_completion(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path, "deep-analysis-notifications.db"))
    with TestClient(app) as client:
        csrf = _login(client)
        _project_id, conversation_id = _conversation(client, csrf, "심층분석")
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert user is not None

            for node_type in ("research", "report"):
                run, _message, _created = create_run(
                    db,
                    user=user,
                    conversation_id=conversation_id,
                    payload=RunCreate(
                        message=RunMessageInput(text=f"{node_type} 노드 실행")
                    ),
                    idempotency_key=f"notification-deep-analysis-{node_type}",
                )
                run.snapshot_json = {
                    **run.snapshot_json,
                    "deep_analysis": {"node_type": node_type},
                }
                transition_run(db, run, PREPARING)
                transition_run(db, run, MODEL_STREAMING)
                db.add(
                    ToolExecution(
                        run_id=run.id,
                        tool_call_id=f"deep-analysis-{node_type}-tool",
                        tool_name="write_file",
                        validated_input_json={},
                        status="completed",
                    )
                )
                transition_run(db, run, COMPLETED)
            db.commit()

        listing = client.get("/api/notifications")
        assert listing.status_code == 200, listing.text
        assert [item["kind"] for item in listing.json()["items"]] == [
            "run_completed"
        ]


def test_failure_approval_and_read_all_notifications(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, "state-notifications.db"))
    with TestClient(app) as client:
        csrf = _login(client)
        _project_id, conversation_id = _conversation(client, csrf, "상태 알림")
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            conversation = db.get(Conversation, conversation_id)
            assert user is not None and conversation is not None
            approval_run, _message, _created = create_run(
                db,
                user=user,
                conversation_id=conversation.id,
                payload=RunCreate(message=RunMessageInput(text="승인 필요 테스트")),
                idempotency_key="notification-approval-0001",
            )
            transition_run(db, approval_run, PREPARING)
            transition_run(db, approval_run, MODEL_STREAMING)
            transition_run(db, approval_run, AWAITING_APPROVAL)

            failed_run, _message, _created = create_run(
                db,
                user=user,
                conversation_id=conversation.id,
                payload=RunCreate(message=RunMessageInput(text="실패 테스트")),
                idempotency_key="notification-failed-0001",
            )
            transition_run(db, failed_run, PREPARING)
            transition_run(db, failed_run, MODEL_STREAMING)
            transition_run(db, failed_run, FAILED)
            db.commit()

        listing = client.get("/api/notifications", params={"unreadOnly": True})
        assert listing.status_code == 200
        assert {item["kind"] for item in listing.json()["items"]} == {
            "run_approval_required",
            "run_failed",
        }
        read_all = client.post("/api/notifications/read-all", headers=csrf)
        assert read_all.status_code == 200, read_all.text
        assert read_all.json()["updatedCount"] == 2
        assert client.get("/api/notifications/unread-count").json()["unreadCount"] == 0
        repeated = client.post("/api/notifications/read-all", headers=csrf)
        assert repeated.status_code == 200
        assert repeated.json()["updatedCount"] == 0
        deleted_all = client.delete("/api/notifications", headers=csrf)
        assert deleted_all.status_code == 204, deleted_all.text
        assert client.get("/api/notifications").json()["items"] == []


def test_notification_rowcount_normalizes_unknown_driver_results() -> None:
    class Result:
        def __init__(self, rowcount: object) -> None:
            self.rowcount = rowcount

    assert notification_service._affected_row_count(Result(3)) == 3
    for rowcount in (-1, None, True, "3"):
        assert notification_service._affected_row_count(Result(rowcount)) == 0


def test_scheduled_run_result_creates_one_deep_link_notification(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path, "scheduled-notifications.db"))
    with TestClient(app) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        task_response = client.post(
            "/api/scheduled-tasks",
            headers=csrf,
            json={
                "projectId": project_id,
                "name": "예약 결과 알림",
                "instructions": "설비 점검 결과를 HTML 보고서로 작성해 주세요.",
                "scheduleKind": "manual",
                "scheduleConfig": {},
                "timezone": "Asia/Seoul",
                "execution": {
                    "providerId": "mock",
                    "modelKey": "mock-agent",
                    "effortId": "medium",
                },
                "extensionSnapshotPolicy": "pinned",
                "deliveryPolicy": {"inApp": True},
                "maxAttempts": 1,
                "timeoutSeconds": 30,
            },
        )
        assert task_response.status_code == 201, task_response.text
        task = task_response.json()
        started = client.post(
            f"/api/scheduled-tasks/{task['id']}/run-now",
            headers={**csrf, "Idempotency-Key": "scheduled-notification-0001"},
        )
        assert started.status_code == 202, started.text
        scheduled = started.json()
        run_id = scheduled["runId"]
        _wait_for_terminal(client, run_id)
        completed_at = datetime.now(UTC)
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            assert run is not None
            run.status = "completed"
            run.error_code = None
            run.error_message = None
            run.started_at = completed_at - timedelta(seconds=2)
            run.finished_at = completed_at
            artifact = Artifact(
                organization_id=run.organization_id,
                project_id=run.project_id,
                conversation_id=run.conversation_id,
                source_run_id=run.id,
                created_by_user_id=run.user_id,
                display_name="예약 결과.html",
                kind="html",
                mime_type="text/html",
                visibility="private",
            )
            db.add(artifact)
            db.commit()

        history = client.get(f"/api/scheduled-tasks/{task['id']}/runs")
        assert history.status_code == 200, history.text
        assert history.json()[0]["status"] == "completed"
        assert client.get(f"/api/scheduled-tasks/{task['id']}/runs").status_code == 200

        notifications = client.get("/api/notifications").json()["items"]
        assert len(notifications) == 1
        notification = notifications[0]
        assert notification["kind"] == "scheduled_run_completed"
        assert notification["deepLink"]["projectId"] == project_id
        assert notification["deepLink"]["runId"] == run_id
        assert notification["deepLink"]["scheduledTaskId"] == task["id"]
        assert notification["deepLink"]["scheduledRunId"] == scheduled["id"]
        assert (
            notification["deepLink"]["artifactId"]
            == history.json()[0]["outputArtifactIds"][0]
        )
