from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from lumina.config import Settings
from lumina.main import create_app


def _login(client: TestClient, login_name: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={"loginName": login_name, "loginDomain": "posco.com", "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def test_help_manual_is_readable_by_users_and_managed_only_by_admins(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        admin_csrf = _login(client, "admin", "1")
        headers = {"X-CSRF-Token": admin_csrf}
        created_user = client.post(
            "/api/admin/users",
            headers=headers,
            json={
                "loginName": "manual-reader",
                "loginDomain": "posco.com",
                "password": "reader-password",
                "displayName": "매뉴얼 독자",
                "affiliation": "AI 플랫폼팀",
                "role": "user",
                "status": "active",
                "mustChangePassword": False,
            },
        )
        assert created_user.status_code == 201, created_user.text

        folder = client.post(
            "/api/help/items",
            headers=headers,
            json={"kind": "folder", "title": "시작하기", "parentId": None},
        )
        assert folder.status_code == 201, folder.text
        document = client.post(
            "/api/help/items",
            headers=headers,
            json={
                "kind": "document",
                "title": "첫 사용 안내",
                "parentId": folder.json()["id"],
                "markdownContent": "# 첫 사용 안내\n\n초안을 확인해 주세요.",
            },
        )
        assert document.status_code == 201, document.text
        updated = client.patch(
            f"/api/help/items/{document.json()['id']}",
            headers=headers,
            json={
                "title": "첫 사용 안내",
                "markdownContent": "# 첫 사용 안내\n\n- 테마 오른쪽의 정보 아이콘을 누릅니다.",
                "expectedRevision": document.json()["revision"],
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == 2

        client.cookies.clear()
        user_csrf = _login(client, "manual-reader", "reader-password")
        listing = client.get("/api/help/items")
        assert listing.status_code == 200, listing.text
        assert listing.json()["canManage"] is False
        assert {item["title"] for item in listing.json()["items"]} == {"시작하기", "첫 사용 안내"}
        manual = next(item for item in listing.json()["items"] if item["kind"] == "document")
        assert "정보 아이콘" in manual["markdownContent"]

        forbidden = client.post(
            "/api/help/items",
            headers={"X-CSRF-Token": user_csrf},
            json={"kind": "document", "title": "권한 없음", "parentId": None},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "admin_required"

        client.cookies.clear()
        admin_csrf = _login(client, "admin", "1")
        deleted = client.delete(
            f"/api/help/items/{folder.json()['id']}",
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert deleted.status_code == 204, deleted.text
        assert client.get("/api/help/items").json()["items"] == []
