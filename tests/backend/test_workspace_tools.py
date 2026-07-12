from __future__ import annotations

from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.agent.executor import LocalRunExecutor, local_run_executor
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import ProjectFile, Run, User
from lumina.providers import MockProvider, MockToolCall
from lumina.runs.approvals import classify_tool_risk
from lumina.tools.workspace import WORKSPACE_TOOL_SCHEMAS, execute_workspace_tool


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'workspace-tools.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"loginName": "admin", "loginDomain": "posco.com", "password": "1"},
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def test_workspace_tool_schemas_and_risk_contract() -> None:
    names = [schema["function"]["name"] for schema in WORKSPACE_TOOL_SCHEMAS]
    assert names == ["glob", "grep", "read_file", "write_file", "list_dir"]
    assert classify_tool_risk("glob", approval_mode="on_risk").effect == "read_only"
    write_risk = classify_tool_risk("write_file", approval_mode="on_risk")
    assert write_risk.effect == "workspace_write"
    assert write_risk.approval_required is False
    assert (
        classify_tool_risk("write_file", approval_mode="confirm_all").approval_required
        is True
    )


def test_workspace_tools_are_project_scoped_and_version_writes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    executor = LocalRunExecutor(settings)
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "workspace tools"},
        ).json()
        upload = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={"logicalPath": "docs/readme.md", "changeReason": "test"},
            files={"file": ("readme.md", b"Alpha\nBeta needle\n", "text/markdown")},
        )
        assert upload.status_code == 201, upload.text
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={**headers, "Idempotency-Key": "workspace-tools-run"},
            json={
                "message": {
                    "text": "inspect files",
                    "attachmentIds": [],
                    "promptReferences": [],
                }
            },
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run"]["runId"]

        with SessionLocal() as db:
            run = db.get(Run, run_id)
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert run is not None and user is not None

            globbed = execute_workspace_tool(
                db,
                executor.file_storage,
                run=run,
                user=user,
                name="glob",
                arguments={"pattern": "**/*.md"},
                max_upload_bytes=settings.max_upload_bytes,
            )
            assert globbed["paths"] == ["docs/readme.md"]

            listed = execute_workspace_tool(
                db,
                executor.file_storage,
                run=run,
                user=user,
                name="list_dir",
                arguments={"path": "docs"},
                max_upload_bytes=settings.max_upload_bytes,
            )
            assert listed["entries"] == [{"name": "readme.md", "type": "file"}]

            read = execute_workspace_tool(
                db,
                executor.file_storage,
                run=run,
                user=user,
                name="read_file",
                arguments={"path": "docs/readme.md", "offset": 2, "limit": 1},
                max_upload_bytes=settings.max_upload_bytes,
            )
            assert read["content"] == "2|Beta needle"

            found = execute_workspace_tool(
                db,
                executor.file_storage,
                run=run,
                user=user,
                name="grep",
                arguments={"query": "NEEDLE", "glob": "**/*.md"},
                max_upload_bytes=settings.max_upload_bytes,
            )
            assert found["matches"][0]["line"] == 2

            written = execute_workspace_tool(
                db,
                executor.file_storage,
                run=run,
                user=user,
                name="write_file",
                arguments={"path": "docs/readme.md", "content": "replacement"},
                max_upload_bytes=settings.max_upload_bytes,
            )
            assert written["action"] == "updated"
            assert written["version"] == 2
            db.commit()

        with SessionLocal() as db:
            project_file = db.scalar(
                select(ProjectFile).where(ProjectFile.project_id == project_id)
            )
            assert project_file is not None
            assert project_file.current_version_number == 2

        with pytest.raises(ValueError, match="Project workspace"):
            with SessionLocal() as db:
                run = db.get(Run, run_id)
                user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
                assert run is not None and user is not None
                execute_workspace_tool(
                    db,
                    executor.file_storage,
                    run=run,
                    user=user,
                    name="glob",
                    arguments={"pattern": "../*"},
                    max_upload_bytes=settings.max_upload_bytes,
                )


def test_glob_tool_call_name_is_persisted_for_ui(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)

    def provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        del wants_artifact
        if first_turn:
            return MockProvider(
                tool_call=MockToolCall(
                    name="glob",
                    arguments={"pattern": "**/*.md"},
                    call_id="glob-ui-check",
                )
            )
        return MockProvider(text_chunks=("확인했습니다.",))

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "glob UI"},
        ).json()
        uploaded = client.post(
            f"/api/projects/{project_id}/files",
            headers=headers,
            data={"logicalPath": "notes/check.md", "changeReason": "test"},
            files={"file": ("check.md", b"check", "text/markdown")},
        )
        assert uploaded.status_code == 201, uploaded.text
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={**headers, "Idempotency-Key": "glob-ui-check-run"},
            json={
                "message": {
                    "text": "glob을 실행해 주세요",
                    "attachmentIds": [],
                    "promptReferences": [],
                }
            },
        )
        assert started.status_code == 202, started.text

        deadline = time.monotonic() + 5
        snapshot = {}
        while time.monotonic() < deadline:
            snapshot = client.get(
                f"/api/runs/{started.json()['run']['runId']}/snapshot"
            ).json()
            if snapshot.get("status") == "completed":
                break
            time.sleep(0.02)

        assert snapshot["status"] == "completed"
        assert snapshot["toolExecutions"][0]["toolName"] == "glob"
        assert snapshot["toolExecutions"][0]["result"]["paths"] == ["notes/check.md"]


def test_write_file_result_is_exposed_as_document_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)

    def provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        del wants_artifact
        if first_turn:
            return MockProvider(
                tool_call=MockToolCall(
                    name="write_file",
                    arguments={"path": "notes/result.md", "content": "# 생성 결과"},
                    call_id="write-file-artifact",
                )
            )
        return MockProvider(text_chunks=("문서를 생성했습니다.",))

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "write_file Artifact"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={**headers, "Idempotency-Key": "write-file-artifact-run"},
            json={"message": {"text": "파일을 만들어 주세요."}},
        )
        assert started.status_code == 202, started.text

        deadline = time.monotonic() + 5
        snapshot = {}
        while time.monotonic() < deadline:
            snapshot = client.get(
                f"/api/runs/{started.json()['run']['runId']}/snapshot"
            ).json()
            if snapshot.get("status") == "completed":
                break
            time.sleep(0.02)

    assert snapshot["status"] == "completed"
    assert snapshot["toolExecutions"][0]["artifactId"] == snapshot["artifacts"][0]["id"]
    assert snapshot["artifacts"][0]["displayName"] == "result.md"
    assert snapshot["artifacts"][0]["mimeType"] == "text/markdown"
