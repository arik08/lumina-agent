from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Project, ProjectSetting, UserSetting


def test_model_candidates_allow_multiple_and_empty_selection(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        cookie_secure=False,
    )

    with TestClient(create_app(settings)) as client:
        login = client.post(
            "/api/auth/login",
            json={
                "loginName": "admin",
                "loginDomain": "posco.com",
                "password": "1",
            },
        )
        assert login.status_code == 200
        headers = {"X-CSRF-Token": login.json()["csrfToken"]}
        project_id = client.get("/api/projects").json()[0]["id"]

        current = client.get(
            "/api/settings/current", params={"project_id": project_id}
        ).json()
        assert set(current["modelCandidates"]) == {"codex", "pgpt"}

        cleared = client.patch(
            "/api/settings/current",
            params={"project_id": project_id},
            headers=headers,
            json={
                "modelCandidates": {},
                "expectedRevision": current["revision"],
            },
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["modelCandidates"] == {}

        selected = client.patch(
            "/api/settings/current",
            params={"project_id": project_id},
            headers=headers,
            json={
                "modelCandidates": {"codex": ["gpt-5.5", "gpt-5.4"]},
                "expectedRevision": cleared.json()["revision"],
            },
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()["modelCandidates"] == {"codex": ["gpt-5.5", "gpt-5.4"]}

        restored = client.get(
            "/api/settings/current", params={"project_id": project_id}
        )
        assert restored.status_code == 200
        assert restored.json()["modelCandidates"] == {"codex": ["gpt-5.5", "gpt-5.4"]}


def test_composer_output_mode_defaults_and_persists(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        cookie_secure=False,
    )

    with TestClient(create_app(settings)) as client:
        login = client.post(
            "/api/auth/login",
            json={"loginName": "admin", "loginDomain": "posco.com", "password": "1"},
        )
        headers = {"X-CSRF-Token": login.json()["csrfToken"]}
        project_id = client.get("/api/projects").json()[0]["id"]
        current = client.get(
            "/api/settings/current", params={"project_id": project_id}
        ).json()
        assert current["outputMode"] == "auto"

        changed = client.patch(
            "/api/settings/current",
            params={"project_id": project_id},
            headers=headers,
            json={"outputMode": "file", "expectedRevision": current["revision"]},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["outputMode"] == "file"

        restored = client.get(
            "/api/settings/current", params={"project_id": project_id}
        )
        assert restored.json()["outputMode"] == "file"


def test_composer_output_mode_uses_project_scope_for_shared_project(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        cookie_secure=False,
    )

    with TestClient(create_app(settings)) as client:
        login = client.post(
            "/api/auth/login",
            json={"loginName": "admin", "loginDomain": "posco.com", "password": "1"},
        )
        headers = {"X-CSRF-Token": login.json()["csrfToken"]}
        project_id = client.get("/api/projects").json()[0]["id"]
        with SessionLocal() as db:
            project = db.get(Project, project_id)
            assert project is not None
            project.project_type = "shared"
            project.visibility = "shared"
            db.commit()

        current = client.get(
            "/api/settings/current", params={"project_id": project_id}
        ).json()
        changed = client.patch(
            "/api/settings/current",
            params={"project_id": project_id},
            headers=headers,
            json={"outputMode": "file", "expectedRevision": current["revision"]},
        )

        assert changed.status_code == 200, changed.text
        assert changed.json()["outputMode"] == "file"
        with SessionLocal() as db:
            project_setting = db.scalar(
                select(ProjectSetting).where(
                    ProjectSetting.project_id == project_id,
                    ProjectSetting.key == "composer.output_mode",
                )
            )
            user_setting = db.scalar(
                select(UserSetting).where(
                    UserSetting.key == "composer.output_mode"
                )
            )
            assert project_setting is not None
            assert project_setting.value_json == "file"
            assert user_setting is None
