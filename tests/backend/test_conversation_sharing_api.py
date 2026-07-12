from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.api.routes import admin, sharing
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import AuditEvent, ConversationShareGrant, Message


def _test_app(tmp_path: Path) -> FastAPI:
    settings = Settings(
        environment="test",
        DATABASE_URL=f"sqlite:///{(tmp_path / 'sharing.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    app = create_app(settings)
    static_mounts = [
        route for route in app.routes if getattr(route, "name", None) == "web"
    ]
    for mount in static_mounts:
        app.router.routes.remove(mount)
    included = [getattr(route, "original_router", None) for route in app.routes]
    if admin.router not in included:
        app.include_router(admin.router, prefix="/api")
    if sharing.router not in included:
        app.include_router(sharing.router, prefix="/api")
    app.router.routes.extend(static_mounts)
    return app


def _login(client: TestClient, login_name: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": login_name,
            "loginDomain": "posco.com",
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def _cookie_snapshot(client: TestClient) -> dict[str, str]:
    return {name: value for name, value in client.cookies.items()}


def _restore_cookies(client: TestClient, cookies: dict[str, str]) -> None:
    client.cookies.clear()
    client.cookies.update(cookies)


def _create_user(client: TestClient, csrf: str, login_name: str) -> None:
    response = client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": csrf},
        json={
            "loginName": login_name,
            "loginDomain": "posco.com",
            "password": "test-password",
            "role": "user",
            "status": "active",
        },
    )
    assert response.status_code == 201, response.text


def _start_and_wait(
    client: TestClient,
    csrf: str,
    conversation_id: str,
    key: str,
    attachment_ids: list[str] | None = None,
) -> dict[str, object]:
    started = client.post(
        f"/api/conversations/{conversation_id}/runs",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": key},
        json={
            "message": {
                "text": "점검 결과를 HTML 보고서로 작성해 주세요.",
                "attachmentIds": attachment_ids or [],
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
        snapshot = client.get(f"/api/runs/{run_id}/snapshot")
        assert snapshot.status_code == 200
        if snapshot.json()["status"] in {"completed", "failed", "cancelled"}:
            assert snapshot.json()["status"] == "completed", snapshot.text
            return snapshot.json()
        time.sleep(0.03)
    raise AssertionError("Run did not complete")


def test_link_snapshot_share_and_revoke(tmp_path: Path) -> None:
    app = _test_app(tmp_path)
    with TestClient(app) as client:
        admin_csrf = _login(client, "admin", "1")
        for login_name in ("alice", "bob", "charlie"):
            _create_user(client, admin_csrf, login_name)

        client.cookies.clear()
        alice_csrf = _login(client, "alice", "test-password")
        alice_cookies = _cookie_snapshot(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": alice_csrf},
            json={"projectId": project_id, "title": "링크 공유"},
        )
        assert conversation.status_code == 201
        conversation_id = conversation.json()["id"]
        attachment = client.post(
            f"/api/conversations/{conversation_id}/attachments",
            headers={"X-CSRF-Token": alice_csrf},
            data={
                "pasted_text": "공유 snapshot에 포함할 점검 원문입니다.",
                "source": "paste",
            },
        )
        assert attachment.status_code == 201, attachment.text
        attachment_id = attachment.json()["id"]
        first_snapshot = _start_and_wait(
            client,
            alice_csrf,
            conversation_id,
            "first-share-run",
            [attachment_id],
        )
        first_artifact_id = first_snapshot["artifacts"][0]["id"]

        with SessionLocal() as db:
            anchor = db.scalar(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.role == "assistant",
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            )
            assert anchor is not None
            anchor_id = anchor.id

        assert (
            client.post(
                "/api/conversation-shares",
                json={
                    "conversationId": conversation_id,
                    "anchorMessageId": anchor_id,
                },
            ).status_code
            == 403
        )
        created = client.post(
            "/api/conversation-shares",
            headers={"X-CSRF-Token": alice_csrf},
            json={
                "conversationId": conversation_id,
                "anchorMessageId": anchor_id,
            },
        )
        assert created.status_code == 201, created.text
        created_payload = created.json()
        share_id = created_payload["id"]
        token = created_payload["urlToken"]
        assert token

        # A later Run must not expand the already-created snapshot.
        _start_and_wait(client, alice_csrf, conversation_id, "second-share-run")

        client.cookies.clear()
        _login(client, "bob", "test-password")
        bob_cookies = _cookie_snapshot(client)
        client.cookies.clear()
        _login(client, "charlie", "test-password")
        charlie_cookies = _cookie_snapshot(client)

        _restore_cookies(client, bob_cookies)
        shared = client.get(f"/api/conversation-shares/{token}")
        assert shared.status_code == 200, shared.text
        payload = shared.json()
        assert payload["share"]["readOnly"] is True
        assert payload["share"]["anchorMessageId"] == anchor_id
        assert payload["conversation"] == {
            "id": conversation_id,
            "title": "링크 공유",
            "ownerDisplayName": None,
        }
        assert len(payload["messages"]) == 2
        assert [artifact["id"] for artifact in payload["artifacts"]] == [
            first_artifact_id
        ]
        assert [item["id"] for item in payload["attachments"]] == [attachment_id]
        assert "projectId" not in shared.text
        assert "previousConversationId" not in shared.text
        assert "nextConversationId" not in shared.text

        _restore_cookies(client, charlie_cookies)
        link_holder = client.get(f"/api/conversation-shares/{token}")
        assert link_holder.status_code == 200
        client.cookies.clear()
        anonymous_link_holder = client.get(f"/api/conversation-shares/{token}")
        assert anonymous_link_holder.status_code == 200
        _restore_cookies(client, bob_cookies)
        assert (
            client.get(f"/api/conversations/{conversation_id}/turn-sets").status_code
            == 404
        )
        bob_csrf = bob_cookies["lumina_csrf"]
        assert (
            client.delete(
                f"/api/conversation-shares/{share_id}",
                headers={"X-CSRF-Token": bob_csrf},
            ).status_code
            == 404
        )

        downloaded = client.get(
            f"/api/conversation-shares/{token}/artifacts/{first_artifact_id}/download"
        )
        assert downloaded.status_code == 200, downloaded.text
        assert "작업 결과 보고서" in downloaded.text
        downloaded_attachment = client.get(
            f"/api/conversation-shares/{token}/attachments/{attachment_id}/download"
        )
        assert downloaded_attachment.status_code == 200
        assert "점검 원문" in downloaded_attachment.text

        _restore_cookies(client, alice_cookies)
        revoked = client.delete(
            f"/api/conversation-shares/{share_id}",
            headers={"X-CSRF-Token": alice_csrf},
        )
        assert revoked.status_code == 204
        _restore_cookies(client, bob_cookies)
        assert client.get(f"/api/conversation-shares/{token}").status_code == 404

        with SessionLocal() as db:
            grant = db.get(ConversationShareGrant, share_id)
            assert grant is not None
            assert grant.token_hash != token
            assert len(grant.token_hash) == 64
            audit_events = list(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.target_type == "conversation_share",
                        AuditEvent.target_id == share_id,
                    )
                )
            )
            actions = {event.action for event in audit_events}
            assert {
                "conversation_share_created",
                "conversation_share_opened",
                "conversation_share_revoked",
            } <= actions
            assert all(token not in str(event.metadata_json) for event in audit_events)
