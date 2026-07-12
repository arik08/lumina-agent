from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.artifacts.service import create_artifact
from lumina.auth.service import create_user
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import ArtifactVersion, Organization, Project, User
from lumina.storage import ManagedLocalStorage


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'artifact-drafts.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _login(
    client: TestClient, login_name: str = "admin", password: str = "1"
) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": login_name,
            "loginDomain": "posco.com",
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def _create_text_artifact(settings: Settings, name: str) -> str:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        project = (
            db.scalar(select(Project).where(Project.owner_user_id == user.id))
            if user
            else None
        )
        assert user is not None and project is not None
        artifact, _version = create_artifact(
            db,
            ManagedLocalStorage(settings.artifacts_dir),
            user=user,
            project_id=project.id,
            conversation_id=None,
            source_run_id=None,
            display_name=f"{name}.md",
            kind="markdown",
            mime_type="text/markdown",
            content=b"committed v1",
        )
        db.commit()
        return artifact.id


def _create_other_admin() -> None:
    with SessionLocal() as db:
        organization_id = db.scalar(
            select(Organization.id).where(Organization.slug == "posco")
        )
        assert organization_id is not None
        create_user(
            db,
            login_name="draft-other",
            password="password",
            organization_id=organization_id,
            role="admin",
        )
        db.commit()


def _version(client: TestClient, artifact_id: str) -> dict[str, object]:
    response = client.get(f"/api/artifacts/{artifact_id}/versions/1")
    assert response.status_code == 200, response.text
    return response.json()


def test_artifact_draft_get_put_cas_stale_and_user_isolation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as first:
        csrf = _login(first)
        artifact_id = _create_text_artifact(settings, "draft-cas")

        missing = first.get(f"/api/artifacts/{artifact_id}/draft")
        assert missing.status_code == 404
        assert missing.json()["code"] == "artifact_draft_not_found"

        created = first.put(
            f"/api/artifacts/{artifact_id}/draft",
            headers=csrf,
            json={"baseVersion": 1, "content": "first draft"},
        )
        assert created.status_code == 200, created.text
        created_payload = created.json()
        assert set(created_payload) == {
            "artifactId",
            "baseVersion",
            "content",
            "etag",
            "updatedAt",
            "stale",
        }
        assert created_payload["content"] == "first draft"
        assert created_payload["stale"] is False

        fetched = first.get(f"/api/artifacts/{artifact_id}/draft")
        assert fetched.status_code == 200
        assert fetched.json() == created_payload

        missing_precondition = first.put(
            f"/api/artifacts/{artifact_id}/draft",
            headers=csrf,
            json={"baseVersion": 1, "content": "must not overwrite"},
        )
        assert missing_precondition.status_code == 428
        assert missing_precondition.json()["code"] == "draft_if_match_required"

        mismatched_base = first.put(
            f"/api/artifacts/{artifact_id}/draft",
            headers={**csrf, "If-Match": created_payload["etag"]},
            json={"baseVersion": 2, "content": "wrong base"},
        )
        assert mismatched_base.status_code == 409
        assert mismatched_base.json()["code"] == "artifact_version_conflict"

        second = TestClient(app)
        try:
            second_csrf = _login(second)
            second_snapshot = second.get(f"/api/artifacts/{artifact_id}/draft").json()
            updated = first.put(
                f"/api/artifacts/{artifact_id}/draft",
                headers={**csrf, "If-Match": created_payload["etag"]},
                json={"baseVersion": 1, "content": "newer draft"},
            )
            assert updated.status_code == 200, updated.text
            lost_update = second.put(
                f"/api/artifacts/{artifact_id}/draft",
                headers={**second_csrf, "If-Match": second_snapshot["etag"]},
                json={"baseVersion": 1, "content": "stale client write"},
            )
            assert lost_update.status_code == 409
            assert lost_update.json()["code"] == "draft_conflict"
        finally:
            second.close()

        current = _version(first, artifact_id)
        committed = first.post(
            f"/api/artifacts/{artifact_id}/versions",
            headers={
                **csrf,
                "If-Match": str(current["etag"]),
                "Idempotency-Key": "leave-stale-draft-0001",
            },
            json={
                "baseVersion": 1,
                "sourceText": "committed v2",
                "changeSummary": "test",
            },
        )
        assert committed.status_code == 201, committed.text
        stale = first.get(f"/api/artifacts/{artifact_id}/draft")
        assert stale.status_code == 200
        assert stale.json()["stale"] is True
        blocked_stale = first.put(
            f"/api/artifacts/{artifact_id}/draft",
            headers={**csrf, "If-Match": stale.json()["etag"]},
            json={"baseVersion": 2, "content": "overwrite stale"},
        )
        assert blocked_stale.status_code == 409
        assert blocked_stale.json()["code"] == "artifact_draft_stale"

        _create_other_admin()
        other = TestClient(app)
        try:
            _login(other, "draft-other", "password")
            assert other.get(f"/api/artifacts/{artifact_id}").status_code == 200
            isolated = other.get(f"/api/artifacts/{artifact_id}/draft")
            assert isolated.status_code == 404
            assert isolated.json()["code"] == "artifact_draft_not_found"
        finally:
            other.close()


def test_version_commit_cleans_only_matching_draft(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        csrf = _login(client)
        matching_id = _create_text_artifact(settings, "matching-cleanup")
        matching = client.put(
            f"/api/artifacts/{matching_id}/draft",
            headers=csrf,
            json={"baseVersion": 1, "content": "matching content"},
        ).json()
        matching_version = _version(client, matching_id)
        saved = client.post(
            f"/api/artifacts/{matching_id}/versions",
            headers={
                **csrf,
                "If-Match": str(matching_version["etag"]),
                "X-Artifact-Draft-If-Match": matching["etag"],
                "Idempotency-Key": "matching-cleanup-0001",
            },
            json={
                "baseVersion": 1,
                "sourceText": "matching content",
                "changeSummary": "test",
            },
        )
        assert saved.status_code == 201, saved.text
        assert client.get(f"/api/artifacts/{matching_id}/draft").status_code == 404

        preserved_id = _create_text_artifact(settings, "preserved-cleanup")
        old = client.put(
            f"/api/artifacts/{preserved_id}/draft",
            headers=csrf,
            json={"baseVersion": 1, "content": "old draft"},
        ).json()
        newer = client.put(
            f"/api/artifacts/{preserved_id}/draft",
            headers={**csrf, "If-Match": old["etag"]},
            json={"baseVersion": 1, "content": "new device draft"},
        )
        assert newer.status_code == 200, newer.text
        preserved_version = _version(client, preserved_id)
        saved_old = client.post(
            f"/api/artifacts/{preserved_id}/versions",
            headers={
                **csrf,
                "If-Match": str(preserved_version["etag"]),
                "X-Artifact-Draft-If-Match": old["etag"],
                "Idempotency-Key": "preserve-newer-draft-0001",
            },
            json={"baseVersion": 1, "sourceText": "old draft", "changeSummary": "test"},
        )
        assert saved_old.status_code == 201, saved_old.text
        preserved = client.get(f"/api/artifacts/{preserved_id}/draft")
        assert preserved.status_code == 200
        assert preserved.json()["content"] == "new device draft"
        assert preserved.json()["stale"] is True


def test_public_edit_cannot_spoof_ai_or_restore_provenance(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        csrf = _login(client)
        artifact_id = _create_text_artifact(settings, "restore-provenance")
        first = _version(client, artifact_id)

        spoofed = client.post(
            f"/api/artifacts/{artifact_id}/versions",
            headers={
                **csrf,
                "If-Match": str(first["etag"]),
                "Idempotency-Key": "spoof-provenance-0001",
            },
            json={
                "baseVersion": 1,
                "sourceText": "spoofed",
                "changeType": "ai_edit",
            },
        )
        assert spoofed.status_code == 422

        edited = client.post(
            f"/api/artifacts/{artifact_id}/versions",
            headers={
                **csrf,
                "If-Match": str(first["etag"]),
                "Idempotency-Key": "manual-version-0001",
            },
            json={"baseVersion": 1, "sourceText": "committed v2"},
        )
        assert edited.status_code == 201, edited.text
        second = edited.json()

        restored = client.post(
            f"/api/artifacts/{artifact_id}/restore",
            headers={
                **csrf,
                "If-Match": str(second["etag"]),
                "Idempotency-Key": "restore-version-0001",
            },
            json={"sourceVersion": 1, "changeSummary": "검증용 복원"},
        )
        assert restored.status_code == 201, restored.text
        restored_payload = restored.json()
        assert restored_payload["version"] == 3
        assert restored_payload["sourceText"] == "committed v1"
        assert restored_payload["changeType"] == "restore"

        with SessionLocal() as db:
            source = db.scalar(
                select(ArtifactVersion).where(
                    ArtifactVersion.artifact_id == artifact_id,
                    ArtifactVersion.version_number == 1,
                )
            )
            version = db.scalar(
                select(ArtifactVersion).where(
                    ArtifactVersion.artifact_id == artifact_id,
                    ArtifactVersion.version_number == 3,
                )
            )
            assert source is not None and version is not None
            assert version.source_version_id == source.id
            assert version.parent_version_id != source.id
