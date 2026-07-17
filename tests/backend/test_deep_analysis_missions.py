from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.auth.service import create_user
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Organization


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
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


def _create_viewer() -> dict[str, str]:
    with SessionLocal() as db:
        organization_id = db.scalar(
            select(Organization.id).where(Organization.slug == "posco")
        )
        assert organization_id is not None
        user = create_user(
            db,
            login_name="deep-analysis-viewer",
            password="password",
            organization_id=organization_id,
            display_name="Deep Analysis Viewer",
            role="user",
            status="active",
        )
        db.commit()
        return {"id": user.id, "loginId": user.login_id}


def _login_viewer(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": "deep-analysis-viewer",
            "loginDomain": "posco.com",
            "password": "password",
        },
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def test_mission_workflow_persists_and_uses_revision_cas(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]

        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=headers,
            json={
                "title": "전사 영업원가 변동 원인 분석",
                "objective": "전년 대비 영업원가 변동의 핵심 원인을 정량적으로 설명한다.",
                "autonomyMode": "balanced",
            },
        )
        assert created.status_code == 201, created.text
        mission = created.json()
        assert mission["revision"] == 1
        assert mission["spentMicrousd"] == 0
        assert mission["workflow"]["revisionNumber"] == 1
        assert [node["nodeKey"] for node in mission["workflow"]["nodes"]] == [
            "N001",
            "N010",
            "N020",
            "N030",
            "N040",
        ]
        assert len(mission["workflow"]["edges"]) == 4

        listing = client.get(f"/api/projects/{project_id}/deep-analysis/missions")
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()] == [mission["id"]]

        restored = client.get(f"/api/deep-analysis/missions/{mission['id']}")
        assert restored.status_code == 200
        assert restored.json()["workflow"]["graphDigest"] == mission["workflow"]["graphDigest"]

        updated = client.patch(
            f"/api/deep-analysis/missions/{mission['id']}",
            headers=headers,
            json={"expectedRevision": 1, "autonomyMode": "guided"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == 2
        assert updated.json()["autonomyMode"] == "guided"

        stale = client.patch(
            f"/api/deep-analysis/missions/{mission['id']}",
            headers=headers,
            json={"expectedRevision": 1, "title": "충돌하는 변경"},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "revision_conflict"
        assert stale.json()["details"] == {"currentRevision": 2}


def test_mission_endpoints_require_auth_and_project_access(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert client.get("/api/projects/missing/deep-analysis/missions").status_code == 401
        headers = _login(client)
        denied = client.post(
            "/api/projects/missing/deep-analysis/missions",
            headers=headers,
            json={"title": "접근 불가"},
        )
        assert denied.status_code == 404


def test_project_viewer_can_read_but_cannot_mutate_missions(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        owner_headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        viewer = _create_viewer()
        membership = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=owner_headers,
            json={"userId": viewer["id"], "role": "viewer"},
        )
        assert membership.status_code == 201, membership.text
        created = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=owner_headers,
            json={"title": "공유 분석"},
        )
        assert created.status_code == 201, created.text
        mission_id = created.json()["id"]

        viewer_headers = _login_viewer(client)
        listing = client.get(f"/api/projects/{project_id}/deep-analysis/missions")
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()] == [mission_id]
        assert client.get(f"/api/deep-analysis/missions/{mission_id}").status_code == 200

        create_denied = client.post(
            f"/api/projects/{project_id}/deep-analysis/missions",
            headers=viewer_headers,
            json={"title": "허용되지 않은 분석"},
        )
        assert create_denied.status_code == 404
        update_denied = client.patch(
            f"/api/deep-analysis/missions/{mission_id}",
            headers=viewer_headers,
            json={"expectedRevision": 1, "title": "허용되지 않은 변경"},
        )
        assert update_denied.status_code == 404
