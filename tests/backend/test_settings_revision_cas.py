from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from lumina.api.errors import ApiProblem
from lumina.api.routes.providers import _claim_settings_revision
from lumina.api.schemas import SettingsPatch
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Project, User


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        cookie_secure=False,
    )


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={"loginName": "admin", "loginDomain": "posco.com", "password": "1"},
    )
    assert response.status_code == 200
    return str(response.json()["csrfToken"])


def _user_and_project(db: Session, project_id: str) -> tuple[User, Project]:
    user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
    project = db.get(Project, project_id)
    assert user is not None
    assert project is not None
    return user, project


def test_personal_settings_claim_rejects_a_stale_writer(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        _login(client)
        project_id = str(client.get("/api/projects").json()[0]["id"])

        with SessionLocal() as winner, SessionLocal() as stale:
            winner_user, winner_project = _user_and_project(winner, project_id)
            stale_user, stale_project = _user_and_project(stale, project_id)
            payload = SettingsPatch(theme="dark", expected_revision="opaque")

            _claim_settings_revision(
                winner,
                user=winner_user,
                project=winner_project,
                payload=payload,
            )
            winner.commit()

            with pytest.raises(ApiProblem) as captured:
                _claim_settings_revision(
                    stale,
                    user=stale_user,
                    project=stale_project,
                    payload=payload,
                )

            assert captured.value.status_code == 409
            assert captured.value.code == "settings_revision_conflict"

        with SessionLocal() as db:
            user, project = _user_and_project(db, project_id)
            assert user.settings_revision == 2
            assert project.settings_revision == 1


def test_shared_settings_claim_uses_the_project_revision(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        _login(client)
        project_id = str(client.get("/api/projects").json()[0]["id"])
        with SessionLocal() as db:
            project = db.get(Project, project_id)
            assert project is not None
            project.project_type = "shared"
            project.visibility = "shared"
            db.commit()

        with SessionLocal() as winner, SessionLocal() as stale:
            winner_user, winner_project = _user_and_project(winner, project_id)
            stale_user, stale_project = _user_and_project(stale, project_id)
            payload = SettingsPatch(output_mode="file", expected_revision="opaque")

            _claim_settings_revision(
                winner,
                user=winner_user,
                project=winner_project,
                payload=payload,
            )
            winner.commit()

            with pytest.raises(ApiProblem) as captured:
                _claim_settings_revision(
                    stale,
                    user=stale_user,
                    project=stale_project,
                    payload=payload,
                )

            assert captured.value.status_code == 409
            assert captured.value.code == "settings_revision_conflict"

        with SessionLocal() as db:
            user, project = _user_and_project(db, project_id)
            assert user.settings_revision == 1
            assert project.settings_revision == 2


def test_settings_api_rejects_a_stale_opaque_revision(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        csrf = _login(client)
        current = client.get("/api/settings/current").json()
        changed = client.patch(
            "/api/settings/current",
            headers={"X-CSRF-Token": csrf},
            json={"theme": "dark", "expectedRevision": current["revision"]},
        )
        assert changed.status_code == 200
        assert changed.json()["revision"] != current["revision"]

        stale = client.patch(
            "/api/settings/current",
            headers={"X-CSRF-Token": csrf},
            json={"theme": "light", "expectedRevision": current["revision"]},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "settings_revision_conflict"


def test_conversation_appearance_settings_are_persisted_per_user(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        csrf = _login(client)
        current = client.get("/api/settings/current").json()
        assert current["conversationWidth"] == 900
        assert current["conversationFontSize"] == 14

        changed = client.patch(
            "/api/settings/current",
            headers={"X-CSRF-Token": csrf},
            json={
                "conversationWidth": 920,
                "conversationFontSize": 16,
                "expectedRevision": current["revision"],
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["conversationWidth"] == 920
        assert changed.json()["conversationFontSize"] == 16

        restored = client.get("/api/settings/current").json()
        assert restored["conversationWidth"] == 920
        assert restored["conversationFontSize"] == 16


def test_composer_work_settings_are_persisted_per_user(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        csrf = _login(client)
        current = client.get("/api/settings/current").json()
        assert current["analysisDepth"] == "auto"
        assert current["answerLength"] == "auto"

        changed = client.patch(
            "/api/settings/current",
            headers={"X-CSRF-Token": csrf},
            json={
                "analysisDepth": "deep",
                "answerLength": "detailed",
                "expectedRevision": current["revision"],
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["analysisDepth"] == "deep"
        assert changed.json()["answerLength"] == "detailed"

        restored = client.get("/api/settings/current").json()
        assert restored["analysisDepth"] == "deep"
        assert restored["answerLength"] == "detailed"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("conversationWidth", 599),
        ("conversationWidth", 1401),
        ("conversationFontSize", 13),
        ("conversationFontSize", 25),
    ),
)
def test_conversation_appearance_settings_enforce_bounds(
    tmp_path: Path, field: str, value: int
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        csrf = _login(client)
        current = client.get("/api/settings/current").json()
        response = client.patch(
            "/api/settings/current",
            headers={"X-CSRF-Token": csrf},
            json={field: value, "expectedRevision": current["revision"]},
        )
        assert response.status_code == 422
