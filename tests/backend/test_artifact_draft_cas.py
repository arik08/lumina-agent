from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from lumina.api.errors import ApiProblem
from lumina.artifacts.service import create_artifact, create_artifact_version
from lumina.auth.service import create_user
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import Artifact, ArtifactVersion, Message, Organization, Project, User
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


def _draft_files(settings: Settings, artifact_id: str) -> list[Path]:
    root = settings.artifacts_dir / "artifact-drafts" / artifact_id
    return [path for path in root.rglob("*") if path.is_file()]


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
        assert len(_draft_files(settings, artifact_id)) == 1

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
            draft_files = _draft_files(settings, artifact_id)
            assert len(draft_files) == 1
            assert draft_files[0].read_text("utf-8") == "newer draft"
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
        assert _draft_files(settings, matching_id) == []

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
        preserved_files = _draft_files(settings, preserved_id)
        assert len(preserved_files) == 1
        assert preserved_files[0].read_text("utf-8") == "new device draft"


def test_draft_commit_failure_cleans_new_storage_content(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        csrf = _login(client)
        artifact_id = _create_text_artifact(settings, "draft-commit-failure")

        with patch.object(
            Session, "commit", side_effect=RuntimeError("forced draft commit failure")
        ):
            with pytest.raises(RuntimeError, match="forced draft commit failure"):
                client.put(
                    f"/api/artifacts/{artifact_id}/draft",
                    headers=csrf,
                    json={"baseVersion": 1, "content": "uncommitted draft"},
                )

        assert client.get(f"/api/artifacts/{artifact_id}/draft").status_code == 404
        assert _draft_files(settings, artifact_id) == []


def test_version_commit_failure_preserves_existing_draft_and_content(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        csrf = _login(client)
        artifact_id = _create_text_artifact(settings, "version-commit-failure")
        draft = client.put(
            f"/api/artifacts/{artifact_id}/draft",
            headers=csrf,
            json={"baseVersion": 1, "content": "preserved draft"},
        ).json()
        current = _version(client, artifact_id)

        with patch.object(
            Session, "commit", side_effect=RuntimeError("forced version commit failure")
        ):
            with pytest.raises(RuntimeError, match="forced version commit failure"):
                client.post(
                    f"/api/artifacts/{artifact_id}/versions",
                    headers={
                        **csrf,
                        "If-Match": str(current["etag"]),
                        "X-Artifact-Draft-If-Match": draft["etag"],
                        "Idempotency-Key": "failed-version-commit-0001",
                    },
                    json={
                        "baseVersion": 1,
                        "sourceText": "preserved draft",
                        "changeSummary": "forced failure",
                    },
                )

        preserved = client.get(f"/api/artifacts/{artifact_id}/draft")
        assert preserved.status_code == 200
        assert preserved.json()["content"] == "preserved draft"
        assert len(_draft_files(settings, artifact_id)) == 1
        version_files = [
            path
            for path in (settings.artifacts_dir / "artifacts" / artifact_id).rglob("*")
            if path.is_file()
        ]
        assert len(version_files) == 1


def test_artifact_version_compare_and_swap_rejects_stale_session(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _login(client)
        artifact_id = _create_text_artifact(settings, "version-cas")
        storage = ManagedLocalStorage(settings.artifacts_dir)

        with SessionLocal() as first_db, SessionLocal() as stale_db:
            first_user = first_db.scalar(
                select(User).where(User.login_id == "admin@posco.com")
            )
            stale_user = stale_db.scalar(
                select(User).where(User.login_id == "admin@posco.com")
            )
            stale_artifact = stale_db.get(Artifact, artifact_id)
            assert first_user is not None and stale_user is not None
            assert stale_artifact is not None
            assert stale_artifact.current_version_number == 1

            winner = create_artifact_version(
                first_db,
                storage,
                user=first_user,
                artifact_id=artifact_id,
                base_version=1,
                content=b"CAS winner",
                change_type="manual_edit",
                change_summary="winner",
            )
            first_db.commit()
            assert winner.version_number == 2

            with pytest.raises(ApiProblem) as conflict:
                create_artifact_version(
                    stale_db,
                    storage,
                    user=stale_user,
                    artifact_id=artifact_id,
                    base_version=1,
                    content=b"stale writer",
                    change_type="manual_edit",
                    change_summary="stale",
                )
            assert conflict.value.code == "artifact_version_conflict"
            assert conflict.value.details == {"currentVersion": 2}

        with SessionLocal() as db:
            persisted = db.get(Artifact, artifact_id)
            versions = list(
                db.scalars(
                    select(ArtifactVersion)
                    .where(ArtifactVersion.artifact_id == artifact_id)
                    .order_by(ArtifactVersion.version_number)
                )
            )
            assert persisted is not None
            assert persisted.current_version_number == 2
            assert [version.version_number for version in versions] == [1, 2]
            assert versions[1].parent_version_id == versions[0].id

        version_files = [
            path
            for path in (settings.artifacts_dir / "artifacts" / artifact_id).rglob("*")
            if path.is_file()
        ]
        assert len(version_files) == 2
        assert {path.read_bytes() for path in version_files} == {
            b"committed v1",
            b"CAS winner",
        }


def test_restore_commit_failure_cleans_new_version_content(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        csrf = _login(client)
        artifact_id = _create_text_artifact(settings, "restore-commit-failure")
        current = _version(client, artifact_id)

        with patch.object(
            Session, "commit", side_effect=RuntimeError("forced restore commit failure")
        ):
            with pytest.raises(RuntimeError, match="forced restore commit failure"):
                client.post(
                    f"/api/artifacts/{artifact_id}/restore",
                    headers={
                        **csrf,
                        "If-Match": str(current["etag"]),
                        "Idempotency-Key": "failed-restore-commit-0001",
                    },
                    json={"sourceVersion": 1, "changeSummary": "forced failure"},
                )

        artifact = client.get(f"/api/artifacts/{artifact_id}")
        assert artifact.status_code == 200
        assert artifact.json()["currentVersion"] == 1
        version_files = [
            path
            for path in (settings.artifacts_dir / "artifacts" / artifact_id).rglob("*")
            if path.is_file()
        ]
        assert len(version_files) == 1
        assert version_files[0].read_bytes() == b"committed v1"


def test_from_message_commit_failure_cleans_created_artifact(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation_response = client.post(
            "/api/conversations",
            headers=csrf,
            json={"projectId": project_id, "title": "Commit cleanup"},
        )
        assert conversation_response.status_code == 201, conversation_response.text
        conversation_id = conversation_response.json()["id"]
        with SessionLocal() as db:
            message = Message(
                conversation_id=conversation_id,
                role="assistant",
                status="completed",
                canonical_text="Artifact commit cleanup",
                turn_index=1,
            )
            db.add(message)
            db.commit()
            message_id = message.id

        with patch.object(
            Session,
            "commit",
            side_effect=RuntimeError("forced from-message commit failure"),
        ):
            with pytest.raises(RuntimeError, match="forced from-message commit failure"):
                client.post(
                    f"/api/artifacts/from-message/{message_id}",
                    headers=csrf,
                )

        listing = client.get("/api/artifacts", params={"project_id": project_id})
        assert listing.status_code == 200
        assert listing.json()["items"] == []
        assert not [
            path for path in settings.artifacts_dir.rglob("*") if path.is_file()
        ]


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
