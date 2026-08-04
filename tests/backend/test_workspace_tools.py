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
from lumina.models import (
    Extension,
    ExtensionDraft,
    ExtensionDraftBinding,
    ProjectFile,
    Run,
    User,
)
from lumina.providers import MockProvider, MockToolCall
from lumina.runs.approvals import classify_tool_risk
from lumina.tools.workspace import (
    ARTIFACT_WRITE_TOOL_SCHEMA,
    WORKSPACE_TOOL_SCHEMAS,
    execute_workspace_tool,
)


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
        json={"loginName": "admin", "loginDomain": "posco.com", "password": "1111"},
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def test_workspace_tool_schemas_and_risk_contract() -> None:
    names = [schema["function"]["name"] for schema in WORKSPACE_TOOL_SCHEMAS]
    assert names == ["glob", "grep", "read_file", "list_dir", "create_skill"]
    create_skill_schema = WORKSPACE_TOOL_SCHEMAS[-1]["function"]
    assert "extensions/skills/<slug>/" in create_skill_schema["description"]
    assert ".skills/" in create_skill_schema["description"]
    assert ARTIFACT_WRITE_TOOL_SCHEMA["function"]["name"] == "write_file"
    assert "without writing to the user-managed Project file repository" in (
        ARTIFACT_WRITE_TOOL_SCHEMA["function"]["description"]
    )
    assert classify_tool_risk("glob", approval_mode="on_risk").effect == "read_only"
    write_risk = classify_tool_risk("write_file", approval_mode="on_risk")
    assert write_risk.effect == "workspace_write"
    assert write_risk.approval_required is False
    assert (
        classify_tool_risk("write_file", approval_mode="confirm_all").approval_required
        is True
    )
    create_skill_risk = classify_tool_risk("create_skill", approval_mode="on_risk")
    assert create_skill_risk.effect == "workspace_write"
    assert create_skill_risk.approval_required is False


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


def test_skill_workspace_writes_register_and_update_active_draft(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    executor = LocalRunExecutor(settings)
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "skill creator"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={**headers, "Idempotency-Key": "workspace-skill-run"},
            json={"message": {"text": "Skill을 만들어 주세요."}},
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run"]["runId"]

        with SessionLocal() as db:
            run = db.get(Run, run_id)
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert run is not None and user is not None
            written = execute_workspace_tool(
                db,
                executor.file_storage,
                run=run,
                user=user,
                name="create_skill",
                arguments={
                    "slug": "daily-standup-helper",
                    "name": "daily-standup-helper",
                    "description": "매일 스탠드업을 정리합니다.",
                    "files": {
                        "SKILL.md": (
                            "---\n"
                            "name: daily-standup-helper\n"
                            "description: 매일 스탠드업을 정리합니다.\n"
                            "---\n\n"
                            "# Daily Standup Helper\n"
                        ),
                        "references/templates.md": "# Standup templates",
                    },
                },
                max_upload_bytes=settings.max_upload_bytes,
            )
            db.commit()

            assert written["slug"] == "daily-standup-helper"
            assert written["revision"] == 1
            assert written["packageRoot"] == (
                "extensions/skills/daily-standup-helper"
            )
            assert {item["path"] for item in written["files"]} == {
                "extensions/skills/daily-standup-helper/SKILL.md",
                "extensions/skills/daily-standup-helper/references/templates.md",
            }

        with SessionLocal() as db:
            extension = db.scalar(
                select(Extension).where(Extension.slug == "daily-standup-helper")
            )
            assert extension is not None
            assert extension.project_id == project_id
            assert extension.name == "daily-standup-helper"
            assert extension.description == "매일 스탠드업을 정리합니다."
            draft = db.scalar(
                select(ExtensionDraft).where(
                    ExtensionDraft.extension_id == extension.id
                )
            )
            assert draft is not None
            assert draft.source_conversation_id == conversation["id"]
            assert set(draft.package_json) == {
                "SKILL.md",
                "references/templates.md",
            }
            binding = db.scalar(
                select(ExtensionDraftBinding).where(
                    ExtensionDraftBinding.draft_id == draft.id,
                    ExtensionDraftBinding.user_id == extension.owner_user_id,
                )
            )
            assert binding is not None and binding.enabled is True
            project_paths = set(
                db.scalars(
                    select(ProjectFile.logical_path).where(
                        ProjectFile.project_id == project_id
                    )
                )
            )
            assert project_paths == {
                "extensions/skills/daily-standup-helper/SKILL.md",
                "extensions/skills/daily-standup-helper/references/templates.md",
            }
            assert not any(path.startswith(".skills/") for path in project_paths)

        suggestions = client.get(
            "/api/composer/suggestions",
            params={"project_id": project_id, "trigger": "$"},
        )
        assert suggestions.status_code == 200, suggestions.text
        candidate = next(
            item
            for item in suggestions.json()["items"]
            if item["insertText"] == "$skill:daily-standup-helper"
        )
        assert candidate["subtitle"] == "Draft r1 · 저장 안 됨"

        with SessionLocal() as db:
            run = db.get(Run, run_id)
            user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert run is not None and user is not None
            updated = execute_workspace_tool(
                db,
                executor.file_storage,
                run=run,
                user=user,
                name="create_skill",
                arguments={
                    "slug": "daily-standup-helper",
                    "name": "daily-standup-helper",
                    "description": "매일 스탠드업을 정리합니다.",
                    "files": {
                        "SKILL.md": (
                            "---\n"
                            "name: daily-standup-helper\n"
                            "description: 매일 스탠드업을 정리합니다.\n"
                            "---\n\n"
                            "# Daily Standup Helper\n"
                        ),
                        "references/templates.md": "# Updated templates",
                    },
                },
                max_upload_bytes=settings.max_upload_bytes,
            )
            db.commit()
            assert updated["revision"] == 2
            assert next(
                item
                for item in updated["files"]
                if item["path"].endswith("references/templates.md")
            )["action"] == "updated"


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


def test_create_skill_tool_persists_package_in_extensions_workspace(
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
                    name="create_skill",
                    arguments={
                        "slug": "say-hello",
                        "name": "say-hello",
                        "description": (
                            "사용자가 간단한 한국어 인사를 요청하면 안녕하세요!라고 "
                            "인사합니다."
                        ),
                        "files": {
                            "SKILL.md": (
                                "---\n"
                                "name: say-hello\n"
                                "description: 사용자가 간단한 한국어 인사를 요청하면 "
                                "안녕하세요!라고 인사합니다.\n"
                                "---\n\n"
                                "# Say Hello\n\n"
                                "Respond with exactly `안녕하세요!`.\n"
                            ),
                            "agents/openai.yaml": (
                                "interface:\n"
                                '  display_name: "Say Hello"\n'
                                '  short_description: "정확한 한국어 인사를 반환합니다"\n'
                                '  default_prompt: "Use $say-hello to greet in Korean."\n'
                                "policy:\n"
                                "  allow_implicit_invocation: true\n"
                            ),
                        },
                    },
                    call_id="create-say-hello-skill",
                )
            )
        return MockProvider(text_chunks=("인사 Skill을 만들었습니다.",))

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "Skill Creator"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={**headers, "Idempotency-Key": "create-say-hello-skill-run"},
            json={"message": {"text": "안녕하세요!라고 인사하는 스킬을 만들어줘"}},
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
        execution = snapshot["toolExecutions"][0]
        assert execution["toolName"] == "create_skill"
        assert execution["result"]["packageRoot"] == "extensions/skills/say-hello"

        with SessionLocal() as db:
            assert set(
                db.scalars(
                    select(ProjectFile.logical_path).where(
                        ProjectFile.project_id == project_id
                    )
                )
            ) == {
                "extensions/skills/say-hello/SKILL.md",
                "extensions/skills/say-hello/agents/openai.yaml",
            }
            extension = db.scalar(select(Extension).where(Extension.slug == "say-hello"))
            assert extension is not None
            assert extension.project_id == project_id
            draft = db.scalar(
                select(ExtensionDraft).where(ExtensionDraft.extension_id == extension.id)
            )
            assert draft is not None
            assert draft.package_json["agents/openai.yaml"].startswith("interface:\n")


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
            json={
                "message": {
                    "text": "파일을 만들어 주세요.",
                    "outputMode": "file",
                    "targetOutputTokens": 10_000,
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
    assert snapshot["toolExecutions"][0]["artifactId"] == snapshot["artifacts"][0]["id"]
    assert snapshot["toolExecutions"][0]["progress"]["tokens"] > 0
    assert snapshot["toolExecutions"][0]["progress"]["lines"] == 1
    assert snapshot["toolExecutions"][0]["durationMs"] >= 100
    assert snapshot["artifacts"][0]["displayName"] == "result.md"
    assert snapshot["artifacts"][0]["mimeType"] == "text/markdown"
    assert snapshot["artifactProgress"] is None
    assert snapshot["artifactUsage"]["tokens"] > 0
    assert snapshot["artifactUsage"]["lines"] == 1
    assert snapshot["artifactUsage"]["estimated"] is False
    assert snapshot["artifactUsage"]["targetTokens"] == 10_000


def test_write_file_allows_executable_html_and_exposes_html_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    html = (
        "<!doctype html><html><head><title>AI Worm</title></head>"
        "<body><canvas id='game'></canvas><script>"
        "document.body.dataset.ready = 'true';"
        "</script></body></html>"
    )

    def provider(
        _provider_id: str, *, wants_artifact: bool, first_turn: bool
    ) -> MockProvider:
        del wants_artifact
        if first_turn:
            return MockProvider(
                tool_call=MockToolCall(
                    name="write_file",
                    arguments={"path": "ai_worm_game.html", "content": html},
                    call_id="write-html-game",
                )
            )
        return MockProvider(text_chunks=("게임을 생성했습니다.",))

    monkeypatch.setattr(local_run_executor, "_provider", provider)
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        conversation = client.post(
            "/api/conversations",
            headers=headers,
            json={"projectId": project_id, "title": "executable HTML game"},
        ).json()
        started = client.post(
            f"/api/conversations/{conversation['id']}/runs",
            headers={**headers, "Idempotency-Key": "write-html-game-run"},
            json={"message": {"text": "실행 가능한 HTML 게임을 만들어 주세요."}},
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
        artifact = snapshot["artifacts"][0]
        assert artifact["displayName"] == "ai_worm_game.html"
        assert artifact["kind"] == "html"
        assert artifact["mimeType"] == "text/html"
        version = client.get(
            f"/api/artifacts/{artifact['id']}/versions/{artifact['currentVersion']}"
        )
        assert version.status_code == 200, version.text
        assert version.json()["sourceText"] == html
        assert version.json()["validationStatus"] == "structural_passed"
        assert version.json()["previewUrl"].endswith(
            f"version={artifact['currentVersion']}"
        )
        metadata_only = client.get(
            f"/api/artifacts/{artifact['id']}/versions/{artifact['currentVersion']}",
            params={"include_source": False},
        )
        assert metadata_only.status_code == 200
        assert metadata_only.json()["sourceAvailable"] is True
        assert metadata_only.json()["sourceText"] is None
        preview = client.get(version.json()["previewUrl"])
        assert preview.status_code == 200, preview.text
        assert preview.headers["content-type"].startswith("text/html")
        assert preview.headers.get("content-encoding") is None
        assert '<script src="/artifact-preview-bridge.js"></script>' in preview.text
        assert preview.text.index("artifact-preview-bridge.js") < preview.text.index(
            "</body>"
        )
        assert html not in preview.text
        standalone_preview = client.get(
            version.json()["previewUrl"],
            params={
                "version": artifact["currentVersion"],
                "standalone": True,
            },
        )
        assert standalone_preview.status_code == 200
        assert standalone_preview.text == html
        assert "artifact-preview-bridge.js" not in standalone_preview.text
        assert standalone_preview.headers["content-disposition"] == "inline"
        assert standalone_preview.headers["content-security-policy"].startswith(
            "sandbox allow-scripts"
        )
