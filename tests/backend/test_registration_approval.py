from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from lumina.config import Settings
from lumina.main import create_app


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        DATABASE_URL=f"sqlite:///{(tmp_path / 'registration.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _login(client: TestClient, login_name: str, password: str):
    return client.post(
        "/api/auth/login",
        json={
            "loginName": login_name,
            "loginDomain": "posco.com",
            "password": password,
        },
    )


def test_registration_requires_admin_approval_and_notifies_bootstrap_admin(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "email": "new.member@posco.com",
                "displayName": "신규 사용자",
                "affiliation": "AI 플랫폼팀",
                "role": "admin",
                "password": "safe-password",
            },
        )
        assert response.status_code == 201, response.text
        assert response.json() == {
            "loginId": "new.member@posco.com",
            "status": "invited",
            "message": "가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.",
        }

        assert _login(client, "new.member", "safe-password").status_code == 401

        admin_session = _login(client, "admin", "1")
        assert admin_session.status_code == 200
        csrf = admin_session.json()["csrfToken"]
        notifications = client.get("/api/notifications").json()["items"]
        registration = next(
            item for item in notifications if item["kind"] == "registration_approval"
        )
        assert registration["title"] == "가입 승인 요청"
        assert "new.member@posco.com" in registration["body"]
        assert registration["deepLink"]["target"] == "admin"

        pending = client.get("/api/admin/users?query=new.member").json()["items"][0]
        assert pending["status"] == "invited"
        assert pending["role"] == "admin"
        assert pending["displayName"] == "신규 사용자"
        assert pending["affiliation"] == "AI 플랫폼팀"

        approved = client.patch(
            f"/api/admin/users/{pending['id']}",
            headers={"X-CSRF-Token": csrf},
            json={"status": "active"},
        )
        assert approved.status_code == 200, approved.text
        assert _login(client, "new.member", "safe-password").status_code == 200


def test_registration_rejects_duplicate_email(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        payload = {
            "email": "duplicate@posco.com",
            "displayName": "중복 신청",
            "affiliation": "AI 플랫폼팀",
            "role": "user",
            "password": "safe-password",
        }
        assert client.post("/api/auth/register", json=payload).status_code == 201
        duplicate = client.post("/api/auth/register", json=payload)
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "login_id_exists"
