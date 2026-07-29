from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from lumina.api.errors import ApiProblem
from lumina.api.routes.help import _update_help_item_record
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import HelpItem, User


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
        admin_csrf = _login(client, "admin", "1111")
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

        moved_to_root = client.patch(
            f"/api/help/items/{document.json()['id']}",
            headers=headers,
            json={
                "title": updated.json()["title"],
                "markdownContent": updated.json()["markdownContent"],
                "parentId": None,
                "expectedRevision": updated.json()["revision"],
            },
        )
        assert moved_to_root.status_code == 200, moved_to_root.text
        assert moved_to_root.json()["parentId"] is None

        moved_back = client.patch(
            f"/api/help/items/{document.json()['id']}",
            headers=headers,
            json={
                "title": moved_to_root.json()["title"],
                "markdownContent": moved_to_root.json()["markdownContent"],
                "parentId": folder.json()["id"],
                "expectedRevision": moved_to_root.json()["revision"],
            },
        )
        assert moved_back.status_code == 200, moved_back.text
        assert moved_back.json()["parentId"] == folder.json()["id"]

        nested_folder = client.post(
            "/api/help/items",
            headers=headers,
            json={"kind": "folder", "title": "하위 폴더", "parentId": folder.json()["id"]},
        )
        assert nested_folder.status_code == 201, nested_folder.text
        cycle = client.patch(
            f"/api/help/items/{folder.json()['id']}",
            headers=headers,
            json={
                "title": folder.json()["title"],
                "markdownContent": "",
                "parentId": nested_folder.json()["id"],
                "expectedRevision": folder.json()["revision"],
            },
        )
        assert cycle.status_code == 422, cycle.text
        assert cycle.json()["code"] == "help_parent_cycle"

        client.cookies.clear()
        user_csrf = _login(client, "manual-reader", "reader-password")
        listing = client.get("/api/help/items")
        assert listing.status_code == 200, listing.text
        assert listing.json()["canManage"] is False
        assert {item["title"] for item in listing.json()["items"]} == {"시작하기", "첫 사용 안내", "하위 폴더"}
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
        admin_csrf = _login(client, "admin", "1111")
        deleted = client.delete(
            f"/api/help/items/{folder.json()['id']}",
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert deleted.status_code == 204, deleted.text
        assert client.get("/api/help/items").json()["items"] == []


def test_help_item_compare_and_swap_rejects_stale_admin_session(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'help-cas.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    with TestClient(create_app(settings)) as client:
        csrf = _login(client, "admin", "1111")
        created = client.post(
            "/api/help/items",
            headers={"X-CSRF-Token": csrf},
            json={
                "kind": "document",
                "title": "CAS 안내",
                "markdownContent": "초기 내용",
            },
        )
        assert created.status_code == 201, created.text
        item_id = created.json()["id"]

        with SessionLocal() as first_db, SessionLocal() as stale_db:
            first_admin = first_db.scalar(
                select(User).where(User.login_id == "admin@posco.com")
            )
            stale_admin = stale_db.scalar(
                select(User).where(User.login_id == "admin@posco.com")
            )
            stale_item = stale_db.get(HelpItem, item_id)
            assert first_admin is not None and stale_admin is not None
            assert stale_item is not None
            assert stale_item.revision == 1

            winner = _update_help_item_record(
                first_db,
                first_admin,
                item_id,
                title="CAS 승자 안내",
                markdown_content="승자 내용",
                expected_revision=1,
            )
            first_db.commit()
            assert winner.revision == 2

            with pytest.raises(ApiProblem) as conflict:
                _update_help_item_record(
                    stale_db,
                    stale_admin,
                    item_id,
                    title="CAS stale 안내",
                    markdown_content="stale 내용",
                    expected_revision=1,
                )
            assert conflict.value.code == "help_revision_conflict"

        persisted = client.get("/api/help/items").json()["items"][0]
        assert persisted["title"] == "CAS 승자 안내"
        assert persisted["markdownContent"] == "승자 내용"
        assert persisted["revision"] == 2
