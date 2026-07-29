from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from lumina.config import Settings
from lumina.main import create_app


def _login(client: TestClient, name: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": name,
            "loginDomain": "posco.com",
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def test_admin_can_force_revoke_share_without_exposing_token(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'admin-share.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        admin_csrf = _login(client, "admin", "1111")
        recipient = client.post(
            "/api/admin/users",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "loginName": "share-recipient",
                "loginDomain": "posco.com",
                "password": "recipient-password",
                "role": "user",
                "status": "active",
                "mustChangePassword": False,
            },
        )
        assert recipient.status_code == 201, recipient.text
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": admin_csrf},
            json={"projectId": project_id, "title": "관리자 회수"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={
                "X-CSRF-Token": admin_csrf,
                "Idempotency-Key": "admin-share-revoke-run-0001",
            },
            json={
                "message": {
                    "text": "공유할 답변을 작성해 주세요.",
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
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = client.get(f"/api/runs/{run_id}/snapshot").json()["status"]
            if status in {"completed", "failed", "cancelled"}:
                assert status == "completed"
                break
            time.sleep(0.02)
        else:
            raise AssertionError("Run did not complete")

        share = client.post(
            "/api/conversation-shares",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "conversationId": conversation["id"],
            },
        )
        assert share.status_code == 201, share.text
        share_id = share.json()["id"]
        token = share.json()["urlToken"]

        revoked = client.request(
            "DELETE",
            f"/api/admin/conversation-shares/{share_id}",
            headers={"X-CSRF-Token": admin_csrf},
            json={"reason": "업무 공유 종료"},
        )
        assert revoked.status_code == 204, revoked.text
        # The operation is idempotent and never returns the one-time URL token.
        repeated = client.request(
            "DELETE",
            f"/api/admin/conversation-shares/{share_id}",
            headers={"X-CSRF-Token": admin_csrf},
            json={"reason": "재확인"},
        )
        assert repeated.status_code == 204
        assert token not in repeated.text

        client.cookies.clear()
        _login(client, "share-recipient", "recipient-password")
        opened = client.get(f"/api/conversation-shares/{token}")
        assert opened.status_code == 404
