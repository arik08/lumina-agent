from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lumina.api.routes import admin
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Message


def _test_app(tmp_path: Path) -> FastAPI:
    settings = Settings(
        environment="test",
        DATABASE_URL=f"sqlite:///{(tmp_path / 'admin.db').as_posix()}",
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
    if not any(
        getattr(route, "original_router", None) is admin.router for route in app.routes
    ):
        app.include_router(admin.router, prefix="/api")
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


def _create_user(
    client: TestClient,
    csrf: str,
    *,
    login_name: str,
    password: str = "initial-password",
    role: str = "user",
) -> dict[str, object]:
    response = client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": csrf},
        json={
            "loginName": login_name,
            "loginDomain": "posco.com",
            "password": password,
            "displayName": login_name.title(),
            "affiliation": "AI 플랫폼팀",
            "role": role,
            "status": "active",
            "mustChangePassword": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_user_lifecycle_permissions_and_audit(tmp_path: Path) -> None:
    app = _test_app(tmp_path)
    with TestClient(app) as admin_client:
        admin_csrf = _login(admin_client, "admin", "1")
        assert (
            admin_client.post(
                "/api/admin/users",
                json={
                    "loginName": "csrf-probe",
                    "loginDomain": "posco.com",
                    "password": "not-created",
                },
            ).status_code
            == 403
        )
        user = _create_user(admin_client, admin_csrf, login_name="operator")
        user_id = str(user["id"])

        listed = admin_client.get("/api/admin/users?query=OPER ATOR")
        assert listed.status_code == 200
        assert listed.json()["items"] == []
        listed = admin_client.get("/api/admin/users?query=OPER")
        assert listed.status_code == 200
        assert [item["loginId"] for item in listed.json()["items"]] == [
            "operator@posco.com"
        ]
        assert listed.json()["items"][0]["affiliation"] == "AI 플랫폼팀"
        assert "passwordHash" not in listed.text

        user_client = TestClient(app)
        try:
            _login(user_client, "operator", "initial-password")
            forbidden = user_client.get("/api/admin/users")
            assert forbidden.status_code == 403

            disabled = admin_client.patch(
                f"/api/admin/users/{user_id}",
                headers={"X-CSRF-Token": admin_csrf},
                json={"status": "disabled"},
            )
            assert disabled.status_code == 200, disabled.text
            assert disabled.json()["status"] == "disabled"
            assert user_client.get("/api/auth/session").status_code == 401

            enabled = admin_client.patch(
                f"/api/admin/users/{user_id}",
                headers={"X-CSRF-Token": admin_csrf},
                json={"status": "active"},
            )
            assert enabled.status_code == 200

            reset = admin_client.post(
                f"/api/admin/users/{user_id}/reset-password",
                headers={"X-CSRF-Token": admin_csrf},
                json={
                    "newPassword": "replacement-password",
                    "mustChangePassword": True,
                },
            )
            assert reset.status_code == 200, reset.text
            assert reset.json()["user"]["mustChangePassword"] is True
            assert "replacement-password" not in reset.text
            assert (
                user_client.post(
                    "/api/auth/login",
                    json={
                        "loginName": "operator",
                        "loginDomain": "posco.com",
                        "password": "initial-password",
                    },
                ).status_code
                == 401
            )
            _login(user_client, "operator", "replacement-password")
        finally:
            user_client.close()

        admin_user = next(
            item
            for item in admin_client.get("/api/admin/users").json()["items"]
            if item["loginId"] == "admin@posco.com"
        )
        last_admin = admin_client.patch(
            f"/api/admin/users/{admin_user['id']}",
            headers={"X-CSRF-Token": admin_csrf},
            json={"status": "disabled"},
        )
        assert last_admin.status_code == 409
        assert last_admin.json()["code"] == "last_active_admin"

        audit = admin_client.get("/api/admin/audit-events?target_id=" + user_id)
        assert audit.status_code == 200
        actions = {item["action"] for item in audit.json()["items"]}
        assert {"user_created", "user_disabled", "password_reset_issued"} <= actions
        actor_by_action = {
            item["action"]: item["actorLoginId"] for item in audit.json()["items"]
        }
        assert actor_by_action["user_created"] == "admin@posco.com"
        assert actor_by_action["password_reset_issued"] == "admin@posco.com"
        assert "operator@posco.com" in actor_by_action.values()
        assert "replacement-password" not in audit.text
        assert "passwordHash" not in audit.text


def test_admin_conversation_view_is_audited(tmp_path: Path) -> None:
    app = _test_app(tmp_path)
    with TestClient(app) as client:
        csrf = _login(client, "admin", "1")
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"projectId": project_id, "title": "관리자 조회 감사 테스트"},
        )
        assert conversation.status_code == 201
        conversation_id = conversation.json()["id"]

        with SessionLocal() as db:
            message = Message(
                conversation_id=conversation_id,
                role="assistant",
                status="completed",
                canonical_text="관리자 의견 조회 대상 답변",
                turn_index=0,
                metadata_json={},
            )
            db.add(message)
            db.commit()
            message_id = message.id

        report = client.post(
            f"/api/messages/{message_id}/reports",
            headers={"X-CSRF-Token": csrf},
            json={"category": "other", "description": "관리 화면에서 확인할 의견"},
        )
        assert report.status_code == 201, report.text

        listing = client.get("/api/admin/conversations?query=조회 감사")
        assert listing.status_code == 200
        assert listing.json()["items"][0]["id"] == conversation_id
        assert listing.json()["items"][0]["feedbackCount"] == 1

        feedback_listing = client.get("/api/admin/conversations?feedback_only=true")
        assert feedback_listing.status_code == 200
        assert [item["id"] for item in feedback_listing.json()["items"]] == [
            conversation_id
        ]

        detail = client.get(f"/api/admin/conversations/{conversation_id}")
        assert detail.status_code == 200
        assert detail.json()["conversation"]["title"] == "관리자 조회 감사 테스트"
        assert detail.json()["feedback"][0]["description"] == "관리 화면에서 확인할 의견"
        assert detail.json()["feedback"][0]["author"]["loginId"] == "admin@posco.com"

        turn_sets = client.get(f"/api/admin/conversations/{conversation_id}/turn-sets")
        assert turn_sets.status_code == 200

        audit = client.get(
            "/api/admin/audit-events"
            f"?action=admin_conversation_viewed&target_id={conversation_id}"
        )
        assert audit.status_code == 200
        assert len(audit.json()["items"]) == 2
