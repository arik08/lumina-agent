from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError

from lumina.agent.executor import LocalRunExecutor
from lumina.api.errors import ApiProblem
from lumina.api.schemas import MessageReferenceInput, RunCreate, RunMessageInput
from lumina.auth import bootstrap_database
from lumina.config import Settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.main import create_app
from lumina.migrations import SERVER_ROOT, upgrade_database
from lumina.models import AuditEvent, MessageReference, Project, ProjectFile, Run, User
from lumina.project_files.service import create_project_file
from lumina.runs.service import create_run
from lumina.storage import ManagedLocalStorage


def _settings(tmp_path: Path, database_name: str = "workspace.db") -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / database_name).as_posix()}",
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


def _upload(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    *,
    logical_path: str,
    content: str,
):
    return client.post(
        f"/api/projects/{project_id}/files",
        headers=headers,
        data={"logicalPath": logical_path, "changeReason": "테스트 업로드"},
        files={"file": (Path(logical_path).name, content.encode(), "text/plain")},
    )


def test_project_file_api_versions_paths_search_and_isolation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]

        traversal = _upload(
            client,
            headers,
            project_id,
            logical_path="../secret.md",
            content="읽으면 안 됩니다.",
        )
        assert traversal.status_code == 422
        assert traversal.json()["code"] == "invalid_project_file_path"

        created = _upload(
            client,
            headers,
            project_id,
            logical_path="Docs/Read Me.md",
            content="첫 버전 점검 내용",
        )
        assert created.status_code == 201, created.text
        first = created.json()
        assert first["currentVersion"] == 1
        assert first["revision"] == 1
        assert first["logicalPath"] == "Docs/Read Me.md"
        assert len(first["contentHash"]) == 64

        duplicate = _upload(
            client,
            headers,
            project_id,
            logical_path="docs/read me.md",
            content="중복 경로",
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "project_file_path_exists"

        listing = client.get(
            f"/api/projects/{project_id}/files", params={"q": "  docs   READ  "}
        )
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()] == [first["id"]]

        version_two = client.post(
            f"/api/projects/{project_id}/files/{first['id']}/versions",
            headers=headers,
            data={"baseVersion": "1", "changeReason": "점검 내용 갱신"},
            files={
                "file": ("read-me.md", "둘째 버전 점검 내용".encode(), "text/plain")
            },
        )
        assert version_two.status_code == 201, version_two.text
        second = version_two.json()
        assert second["currentVersion"] == 2
        assert second["revision"] == 2
        assert second["contentHash"] != first["contentHash"]

        stale = client.post(
            f"/api/projects/{project_id}/files/{first['id']}/versions",
            headers=headers,
            data={"baseVersion": "1"},
            files={"file": ("read-me.md", "경합 버전".encode(), "text/plain")},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "project_file_version_conflict"
        assert stale.json()["details"]["currentVersion"] == 2

        old_download = client.get(
            f"/api/projects/{project_id}/files/{first['id']}/download",
            params={"version": 1},
        )
        assert old_download.status_code == 200
        assert old_download.content == "첫 버전 점검 내용".encode()

        extension_change = client.patch(
            f"/api/projects/{project_id}/files/{first['id']}",
            headers=headers,
            json={"logicalPath": "reports/summary.txt", "expectedRevision": 2},
        )
        assert extension_change.status_code == 409
        assert extension_change.json()["code"] == "project_file_extension_mismatch"

        moved = client.patch(
            f"/api/projects/{project_id}/files/{first['id']}",
            headers=headers,
            json={"logicalPath": "reports/summary.md", "expectedRevision": 2},
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["logicalPath"] == "reports/summary.md"
        assert moved.json()["revision"] == 3

        stale_move = client.patch(
            f"/api/projects/{project_id}/files/{first['id']}",
            headers=headers,
            json={"logicalPath": "reports/stale.md", "expectedRevision": 2},
        )
        assert stale_move.status_code == 409
        assert stale_move.json()["code"] == "project_file_revision_conflict"

        detail = client.get(f"/api/projects/{project_id}/files/{first['id']}")
        assert detail.status_code == 200
        assert [item["version"] for item in detail.json()["versions"]] == [2, 1]

        other_project = client.post(
            "/api/projects",
            headers=headers,
            json={"name": "격리 Project", "description": ""},
        )
        assert other_project.status_code == 201
        isolated = client.get(
            f"/api/projects/{other_project.json()['id']}/files/{first['id']}"
        )
        assert isolated.status_code == 404

        deleted = client.delete(
            f"/api/projects/{project_id}/files/{first['id']}",
            headers=headers,
            params={"expectedRevision": 3},
        )
        assert deleted.status_code == 204
        assert client.get(f"/api/projects/{project_id}/files").json() == []
        trash = client.get(
            f"/api/projects/{project_id}/files",
            params={"includeDeleted": "true"},
        ).json()
        assert trash[0]["status"] == "deleted"
        assert trash[0]["revision"] == 4

        reused = _upload(
            client,
            headers,
            project_id,
            logical_path="reports/summary.md",
            content="새 파일",
        )
        assert reused.status_code == 201, reused.text
        assert reused.json()["id"] != first["id"]

    with SessionLocal() as db:
        audit_actions = {event.action for event in db.scalars(select(AuditEvent))}
        assert {
            "project_file_created",
            "project_file_version_created",
            "project_file_moved",
            "project_file_deleted",
        } <= audit_actions


def test_composer_and_run_pin_exact_project_file_version_and_project(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, "snapshot.db")
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project = client.get("/api/projects").json()[0]
        project_id = project["id"]
        updated = client.patch(
            f"/api/projects/{project_id}",
            headers=headers,
            json={"concept": "광양 설비 점검 기준을 적용합니다."},
        )
        assert updated.status_code == 200
        updated_project = updated.json()
        uploaded = _upload(
            client,
            headers,
            project_id,
            logical_path="inspection/checklist.md",
            content="첫 버전 기준: 베어링 온도 확인",
        ).json()

        suggestions = client.get(
            "/api/composer/suggestions",
            params={"project_id": project_id, "trigger": "@"},
        )
        assert suggestions.status_code == 200
        candidate = suggestions.json()["items"][0]
        assert candidate["id"] == uploaded["id"]
        assert candidate["versionOrDigest"] == uploaded["contentHash"]
        assert candidate["displaySnapshot"] == {
            "name": "checklist.md",
            "targetType": "project_file",
            "logicalPath": "inspection/checklist.md",
            "mimeType": "text/markdown",
            "version": 1,
            "versionId": candidate["displaySnapshot"]["versionId"],
            "contentHash": uploaded["contentHash"],
        }

        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "Project file snapshot"},
        ).json()

        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert admin is not None
            run, message, created = create_run(
                db,
                user=admin,
                conversation_id=conversation["id"],
                payload=RunCreate(
                    message=RunMessageInput(
                        text="@checklist.md 기준을 적용해 주세요.",
                        prompt_references=[
                            MessageReferenceInput(
                                kind="file",
                                reference_id=uploaded["id"],
                                version_or_digest=uploaded["contentHash"],
                            )
                        ],
                    )
                ),
                idempotency_key="project-file-snapshot-1",
            )
            db.commit()
            run_id = run.id
            message_id = message.id
            assert created is True
            assert run.snapshot_json["project"] == {
                "id": project_id,
                "concept": "광양 설비 점검 기준을 적용합니다.",
                "concept_revision": updated_project["conceptRevision"],
                "concept_hash": updated_project["conceptHash"],
                "updated_at": run.snapshot_json["project"]["updated_at"],
            }
            assert (
                run.snapshot_json["project_files"][0]["version_or_digest"]
                == uploaded["contentHash"]
            )

        version_two = client.post(
            f"/api/projects/{project_id}/files/{uploaded['id']}/versions",
            headers=headers,
            data={"baseVersion": "1"},
            files={"file": ("checklist.md", "둘째 버전 기준".encode(), "text/plain")},
        )
        assert version_two.status_code == 201
        client.patch(
            f"/api/projects/{project_id}",
            headers=headers,
            json={"concept": "변경된 Project concept"},
        )

        with SessionLocal() as db:
            loaded_run = db.get(Run, run_id)
            reference = db.scalar(
                select(MessageReference).where(
                    MessageReference.message_id == message_id
                )
            )
            assert loaded_run is not None and reference is not None
            assert (
                loaded_run.snapshot_json["project"]["concept"]
                == "광양 설비 점검 기준을 적용합니다."
            )
            assert reference.reference_id == uploaded["id"]
            assert reference.version_or_digest == uploaded["contentHash"]
            assert reference.display_snapshot_json["version"] == 1

        prepared = LocalRunExecutor(settings)._message_with_context(
            "기준을 확인합니다.",
            attachment_ids=[],
            prompt_references=loaded_run.snapshot_json["prompt_references"],
            extensions=[],
        )
        assert "첫 버전 기준: 베어링 온도 확인" in prepared
        assert "둘째 버전 기준" not in prepared

        deleted = client.delete(
            f"/api/projects/{project_id}/files/{uploaded['id']}",
            headers=headers,
            params={"expectedRevision": version_two.json()["revision"]},
        )
        assert deleted.status_code == 204
        stored_reference = client.get(f"/api/messages/{message_id}/references")
        assert stored_reference.status_code == 200
        assert stored_reference.json()[0]["validationStatus"] == "unavailable"
        assert stored_reference.json()[0]["displaySnapshot"]["logicalPath"] == (
            "inspection/checklist.md"
        )

        with SessionLocal() as db:
            referenced_audit = db.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "project_file_referenced",
                    AuditEvent.target_id == uploaded["id"],
                )
            )
            assert referenced_audit is not None


def test_failed_database_commit_cleans_managed_storage_objects(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "cleanup.db")
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)
    storage = ManagedLocalStorage(settings.files_dir or tmp_path / "files")

    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert admin is not None
        project = db.scalar(select(Project).where(Project.owner_user_id == admin.id))
        assert project is not None
        failure = IntegrityError("INSERT", {}, RuntimeError("forced unique conflict"))
        original_flush = db.flush

        def fail_project_file_flush(*args, **kwargs):
            if any(isinstance(item, ProjectFile) for item in db.new):
                raise failure
            return original_flush(*args, **kwargs)

        with patch.object(db, "flush", side_effect=fail_project_file_flush):
            with pytest.raises(ApiProblem) as error:
                create_project_file(
                    db,
                    user=admin,
                    project_id=project.id,
                    logical_path="cleanup/test.md",
                    original_filename="test.md",
                    content="정리할 내용".encode(),
                    change_reason="cleanup test",
                    max_upload_bytes=settings.max_upload_bytes,
                    storage=storage,
                )
        assert error.value.code == "project_file_path_exists"

    assert [
        path for path in (settings.files_dir or tmp_path).rglob("*") if path.is_file()
    ] == []
    with SessionLocal() as db:
        assert db.scalar(select(ProjectFile)) is None


def test_project_workspace_migration_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "workspace-migration.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url)
    engine = create_engine(database_url)
    try:
        assert {"project_files", "project_file_versions"} <= set(
            inspect(engine).get_table_names()
        )
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0013"
            )
    finally:
        engine.dispose()

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.downgrade(config, "0006")
    engine = create_engine(database_url)
    try:
        assert {"project_files", "project_file_versions"}.isdisjoint(
            inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        assert {"project_files", "project_file_versions"} <= set(
            inspect(engine).get_table_names()
        )
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0013"
            )
    finally:
        engine.dispose()
