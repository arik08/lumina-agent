from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
from lumina.tools.source_documents import project_file_source_document_id


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


@pytest.mark.parametrize("content", ["", "   \n\t"])
def test_project_file_api_accepts_blank_text_files(
    tmp_path: Path, content: str
) -> None:
    settings = _settings(tmp_path, "blank-project-file.db")
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]

        created = _upload(
            client,
            headers,
            project_id,
            logical_path="notes/blank.md",
            content=content,
        )

        assert created.status_code == 201, created.text
        payload = created.json()
        assert payload["logicalPath"] == "notes/blank.md"
        assert payload["size"] == len(content.encode())
        downloaded = client.get(
            f"/api/projects/{project_id}/files/{payload['id']}/download"
        )
        assert downloaded.status_code == 200
        assert downloaded.content == content.encode()


def test_project_file_api_rejects_html_document_with_markdown_extension(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, "html-as-markdown.db")
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]

        created = _upload(
            client,
            headers,
            project_id,
            logical_path="reports/intermediate.md",
            content=" \n<!doctype html><html><body>wrong format</body></html>",
        )

        assert created.status_code == 415
        assert created.json()["code"] == "mime_mismatch"


def test_project_file_html_preview_opens_inline_with_sandbox(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, "html-project-file-preview.db")
    html = (
        "<!doctype html><html><head><title>보고서</title></head><body>"
        '<div class="mermaid">flowchart TD\nA-->B</div></body></html>'
    )
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={"logicalPath": "reports/final.html", "changeReason": "최종 보고서"},
            files={"file": ("final.html", html.encode(), "text/html")},
        )
        assert created.status_code == 201, created.text

        preview = client.get(
            f"/api/projects/{project_id}/files/{created.json()['id']}/preview"
        )

        assert preview.status_code == 200
        assert 'data-lumina-standalone-mermaid="11.16.0"' in preview.text
        assert preview.headers["content-disposition"] == "inline"
        assert preview.headers["content-security-policy"].startswith(
            "sandbox allow-scripts"
        )

        downloaded = client.get(
            f"/api/projects/{project_id}/files/{created.json()['id']}/download",
            headers={"Accept-Encoding": "identity"},
        )

        assert downloaded.status_code == 200
        assert 'data-lumina-standalone-mermaid="11.16.0"' in downloaded.text
        assert downloaded.headers["content-length"] == str(len(downloaded.content))
        assert downloaded.headers["etag"] != f'"{created.json()["contentHash"]}"'
        stored_html = next(
            path
            for path in (settings.files_dir / "project-files").rglob("*")
            if path.is_file() and path.read_bytes() == html.encode()
        )
        assert "cdn.jsdelivr.net/npm/mermaid" not in stored_html.read_text("utf-8")


def test_project_file_api_keyset_pages_without_duplicates(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "project-file-pages.db")
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created_ids = {
            _upload(
                client,
                headers,
                project_id,
                logical_path=f"pages/{index}.txt",
                content=f"page {index}",
            ).json()["id"]
            for index in range(3)
        }

        first = client.get(
            f"/api/projects/{project_id}/files",
            params={"page": True, "limit": 2},
        )
        assert first.status_code == 200, first.text
        assert len(first.json()["items"]) == 2
        assert first.json()["nextCursor"]

        second = client.get(
            f"/api/projects/{project_id}/files",
            params={
                "page": True,
                "limit": 2,
                "cursor": first.json()["nextCursor"],
            },
        )
        assert second.status_code == 200, second.text
        assert len(second.json()["items"]) == 1
        assert second.json()["nextCursor"] is None
        listed_ids = {
            item["id"] for item in first.json()["items"] + second.json()["items"]
        }
        assert listed_ids == created_ids

        invalid = client.get(
            f"/api/projects/{project_id}/files",
            params={"page": True, "cursor": "not-a-cursor"},
        )
        assert invalid.status_code == 400
        assert invalid.json()["code"] == "invalid_file_cursor"


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
        stored_version_one = next(
            path
            for path in (settings.files_dir / "project-files").rglob("*")
            if path.is_file() and path.read_bytes() == "첫 버전 점검 내용".encode()
        )
        stored_version_one.write_bytes(b"tampered project file")
        unavailable = client.get(
            f"/api/projects/{project_id}/files/{first['id']}/download",
            params={"version": 1},
        )
        assert unavailable.status_code == 503
        assert unavailable.json()["code"] == "project_file_content_missing"

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
        suggestion_items = suggestions.json()["items"]
        candidate = next(item for item in suggestion_items if item["id"] == uploaded["id"])
        folder_candidate = next(item for item in suggestion_items if item["kind"] == "folder")
        assert folder_candidate["name"] == "inspection"
        assert folder_candidate["displaySnapshot"]["logicalPath"] == "inspection"
        assert folder_candidate["displaySnapshot"]["fileCount"] == 1
        assert folder_candidate["displaySnapshot"]["fileVersions"] == [
            {
                "id": uploaded["id"],
                "path": "inspection/checklist.md",
                "digest": uploaded["contentHash"],
            }
        ]
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

        folder_conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "Project folder snapshot"},
        ).json()
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert admin is not None
            folder_run, folder_message, folder_created = create_run(
                db,
                user=admin,
                conversation_id=folder_conversation["id"],
                payload=RunCreate(
                    message=RunMessageInput(
                        text="@inspection 폴더를 적용해 주세요.",
                        prompt_references=[
                            MessageReferenceInput(
                                kind="folder",
                                reference_id=folder_candidate["id"],
                                version_or_digest=folder_candidate["versionOrDigest"],
                            )
                        ],
                    )
                ),
                idempotency_key="project-folder-snapshot-1",
            )
            db.commit()
            assert folder_created is True
            assert folder_run.snapshot_json["project_files"] == []
            folder_reference = db.scalar(
                select(MessageReference).where(
                    MessageReference.message_id == folder_message.id
                )
            )
            assert folder_reference is not None
            assert folder_reference.kind == "folder"
            assert folder_reference.display_snapshot_json["logicalPath"] == "inspection"
            assert folder_reference.display_snapshot_json["fileVersions"] == [
                {
                    "id": uploaded["id"],
                    "path": "inspection/checklist.md",
                    "digest": uploaded["contentHash"],
                }
            ]

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
        assert "첫 버전 기준: 베어링 온도 확인" not in prepared
        assert "둘째 버전 기준" not in prepared
        assert "<source-document-index>" in prepared
        assert project_file_source_document_id(
            uploaded["id"], uploaded["contentHash"]
        ) in prepared

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


def test_project_folder_api_creates_moves_and_deletes_nested_files(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "folders.db")
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]

        created = client.post(
            f"/api/projects/{project_id}/files/folders",
            headers=headers,
            json={"logicalPath": "Inbox"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["logicalPath"] == "Inbox"

        uploaded = _upload(
            client,
            headers,
            project_id,
            logical_path="Inbox/note.md",
            content="이동할 내용",
        )
        assert uploaded.status_code == 201, uploaded.text
        archive = client.post(
            f"/api/projects/{project_id}/files/folders",
            headers=headers,
            json={"logicalPath": "Archive"},
        )
        assert archive.status_code == 201, archive.text

        moved = client.patch(
            f"/api/projects/{project_id}/files/folders",
            headers=headers,
            json={"sourcePath": "Inbox", "targetPath": "Archive/Inbox"},
        )
        assert moved.status_code == 200, moved.text
        assert moved.json() == {"fileCount": 1, "folderCount": 1}
        assert client.get(f"/api/projects/{project_id}/files").json()[0][
            "logicalPath"
        ] == "Archive/Inbox/note.md"
        assert {folder["logicalPath"] for folder in client.get(
            f"/api/projects/{project_id}/files/folders"
        ).json()} == {"Archive", "Archive/Inbox"}

        descendant = client.patch(
            f"/api/projects/{project_id}/files/folders",
            headers=headers,
            json={
                "sourcePath": "Archive",
                "targetPath": "Archive/Inbox/Archive",
            },
        )
        assert descendant.status_code == 422
        assert descendant.json()["code"] == "invalid_project_folder_target"

        deleted = client.delete(
            f"/api/projects/{project_id}/files/folders",
            headers=headers,
            params={"logicalPath": "Archive/Inbox"},
        )
        assert deleted.status_code == 204
        assert client.get(f"/api/projects/{project_id}/files").json() == []
        assert [folder["logicalPath"] for folder in client.get(
            f"/api/projects/{project_id}/files/folders"
        ).json()] == ["Archive"]

    with SessionLocal() as db:
        audit_actions = {event.action for event in db.scalars(select(AuditEvent))}
        assert {
            "project_folder_created",
            "project_folder_moved",
            "project_folder_deleted",
        } <= audit_actions


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


def test_unexpected_database_flush_cleans_managed_storage_objects(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, "unexpected-flush-cleanup.db")
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)
    storage = ManagedLocalStorage(settings.files_dir or tmp_path / "files")

    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert admin is not None
        project = db.scalar(select(Project).where(Project.owner_user_id == admin.id))
        assert project is not None
        original_flush = db.flush

        def fail_project_file_flush(*args, **kwargs):
            if any(isinstance(item, ProjectFile) for item in db.new):
                raise RuntimeError("forced project file flush failure")
            return original_flush(*args, **kwargs)

        with patch.object(db, "flush", side_effect=fail_project_file_flush):
            with pytest.raises(RuntimeError, match="forced project file flush failure"):
                create_project_file(
                    db,
                    user=admin,
                    project_id=project.id,
                    logical_path="cleanup/unexpected.md",
                    original_filename="unexpected.md",
                    content="unexpected cleanup".encode(),
                    change_reason="cleanup test",
                    max_upload_bytes=settings.max_upload_bytes,
                    storage=storage,
                )

    assert not [path for path in storage.root.rglob("*") if path.is_file()]


def test_project_file_commit_failures_clean_only_new_storage_objects(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, "route-commit-cleanup.db")
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]

        with patch.object(
            Session, "commit", side_effect=RuntimeError("forced create commit failure")
        ):
            with pytest.raises(RuntimeError, match="forced create commit failure"):
                _upload(
                    client,
                    headers,
                    project_id,
                    logical_path="cleanup/create.md",
                    content="uncommitted create",
                )

        assert client.get(f"/api/projects/{project_id}/files").json() == []
        assert not [
            path for path in settings.files_dir.rglob("*") if path.is_file()
        ]

        created = _upload(
            client,
            headers,
            project_id,
            logical_path="cleanup/version.md",
            content="committed version one",
        )
        assert created.status_code == 201, created.text
        project_file = created.json()
        committed_files = {
            path for path in settings.files_dir.rglob("*") if path.is_file()
        }

        with patch.object(
            Session, "commit", side_effect=RuntimeError("forced version commit failure")
        ):
            with pytest.raises(RuntimeError, match="forced version commit failure"):
                client.post(
                    f"/api/projects/{project_id}/files/{project_file['id']}/versions",
                    headers=headers,
                    data={"baseVersion": 1, "changeReason": "forced failure"},
                    files={
                        "file": (
                            "version.md",
                            b"uncommitted version two",
                            "text/markdown",
                        )
                    },
                )

        detail = client.get(
            f"/api/projects/{project_id}/files/{project_file['id']}"
        )
        assert detail.status_code == 200
        assert detail.json()["currentVersion"] == 1
        assert {
            path for path in settings.files_dir.rglob("*") if path.is_file()
        } == committed_files


def test_project_workspace_migration_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "workspace-migration.db"
    database_url = f"sqlite:///{database.as_posix()}"
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    upgrade_database(database_url)
    engine = create_engine(database_url)
    try:
        assert {"project_files", "project_file_versions", "project_folders"} <= set(
            inspect(engine).get_table_names()
        )
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision()
                == expected_head
            )
    finally:
        engine.dispose()

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
                MigrationContext.configure(connection).get_current_revision()
                == expected_head
            )
    finally:
        engine.dispose()
