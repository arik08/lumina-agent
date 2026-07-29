from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.api.errors import ApiProblem, install_error_handlers
from lumina.api.routes import auth, extensions, projects, schedules
from lumina.agent.executor import LocalRunExecutor
from lumina.auth import bootstrap_database, create_user
from lumina.config import Settings, get_settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.extensions import repository_catalog
from lumina.extensions.service import save_draft_version, update_draft
from lumina.mcp.service import install_definition, resolve_mcp_snapshot
from lumina.models import (
    Artifact,
    AuditEvent,
    Conversation,
    Extension,
    ExtensionDraft,
    ExtensionDraftBinding,
    ExtensionDraftRevision,
    ExtensionInstallation,
    ExtensionVersion,
    McpDefinition,
    McpInstallation,
    Organization,
    Project,
    Run,
    RunCommand,
    ScheduledRun,
    ScheduledTask,
    SkillFolderPlacement,
    SkillOwnership,
    User,
    utc_now,
)
from lumina.schedules.service import (
    dispatch_due_tasks,
    maintain_scheduled_runs,
    next_occurrence,
    scheduled_run_payload,
    start_scheduled_run,
)
from lumina.schedules import service as schedules_service


def _test_app(tmp_path: Path) -> tuple[FastAPI, Settings]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lumina.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)
    application = FastAPI()
    application.state.settings = settings
    application.dependency_overrides[get_settings] = lambda: settings
    install_error_handlers(application)
    for module in (auth, projects, extensions, schedules):
        application.include_router(module.router, prefix="/api")
    return application, settings


def _login(client: TestClient, name: str = "admin", password: str = "1111") -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": name,
            "loginDomain": "posco.com",
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrfToken"])


def _create_manual_scheduled_run(
    client: TestClient,
    *,
    csrf: str,
    name: str,
    idempotency_key: str,
    max_attempts: int,
    timeout_seconds: int = 30,
) -> tuple[dict[str, object], dict[str, object]]:
    project_id = client.get("/api/projects").json()[0]["id"]
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/scheduled-tasks",
        headers=headers,
        json={
            "projectId": project_id,
            "name": name,
            "instructions": f"{name} 결과를 HTML 보고서로 작성해 주세요.",
            "scheduleKind": "manual",
            "scheduleConfig": {},
            "timezone": "Asia/Seoul",
            "execution": {
                "providerId": "mock",
                "modelKey": "mock-agent",
                "effortId": "medium",
            },
            "extensionSnapshotPolicy": "pinned",
            "deliveryPolicy": {"projectHistory": True},
            "maxAttempts": max_attempts,
            "timeoutSeconds": timeout_seconds,
        },
    )
    assert created.status_code == 201, created.text
    task = created.json()
    started = client.post(
        f"/api/scheduled-tasks/{task['id']}/run-now",
        headers={**headers, "Idempotency-Key": idempotency_key},
    )
    assert started.status_code == 202, started.text
    return task, started.json()


def test_marketplace_refresh_syncs_new_repository_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = tmp_path / "repository"
    skills_root = repository_root / "extensions" / "skills"
    skills_root.mkdir(parents=True)
    (skills_root / "catalog.json").write_text(
        json.dumps(
            {
                "explorer-added": {
                    "description": "카탈로그에 표시할 한국어 설명",
                    "tags": [],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(repository_catalog, "REPOSITORY_ROOT", repository_root)

    app, _settings = _test_app(tmp_path)
    with TestClient(app) as client:
        csrf = _login(client)
        assert client.get("/api/extensions").json() == []

        skill_root = skills_root / "explorer-added"
        skill_root.mkdir()
        (skill_root / "SKILL.md").write_text(
            "---\nname: explorer-added\ndescription: English runtime trigger description.\n---\n\n# Explorer Added\n",
            encoding="utf-8",
        )

        synced = client.post(
            "/api/extensions/repository-sync",
            headers={"X-CSRF-Token": csrf},
        )
        assert synced.status_code == 200, synced.text
        assert synced.json()["skillsChanged"] == 1
        assert synced.json()["mcpChanged"] == 0
        assert synced.json()["revision"]

        catalog = client.get("/api/extensions").json()
        assert [(item["slug"], item["description"]) for item in catalog] == [
            ("explorer-added", "카탈로그에 표시할 한국어 설명")
        ]

        repeated = client.post(
            "/api/extensions/repository-sync",
            headers={"X-CSRF-Token": csrf},
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["skillsChanged"] == 0
        assert repeated.json()["mcpChanged"] == 0
        assert repeated.json()["revision"] == synced.json()["revision"]


def test_repository_mcp_wrapper_is_classified_and_attached_to_mcp_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = tmp_path / "repository"
    skills_root = repository_root / "extensions" / "skills"
    mcp_root = repository_root / "extensions" / "mcp"
    skills_root.mkdir(parents=True)
    mcp_root.mkdir(parents=True)
    monkeypatch.setattr(repository_catalog, "REPOSITORY_ROOT", repository_root)

    app, _settings = _test_app(tmp_path)
    with TestClient(app) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        wrapper_root = skills_root / "internal-search"
        wrapper_root.mkdir()
        (wrapper_root / "SKILL.md").write_text(
            "---\n"
            "name: internal-search\n"
            "description: 승인된 사내 문서를 검색합니다.\n"
            "metadata:\n"
            "  lumina-source: skill-mcp:internal-search\n"
            "---\n\n"
            "# Internal Search\n\n반드시 MCP 검색 결과만 근거로 답합니다.\n",
            encoding="utf-8",
        )
        (mcp_root / "internal-search.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "internal-search": {
                            "type": "stdio",
                            "command": "python",
                            "args": ["internal_search.py"],
                            "cwd": ".",
                            "description": "승인된 사내 문서를 검색합니다.",
                            "tools": [
                                {
                                    "name": "search_docs",
                                    "description": "문서 검색",
                                    "input_schema": {"type": "object"},
                                }
                            ],
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        synced = client.post(
            "/api/extensions/repository-sync",
            headers={"X-CSRF-Token": csrf},
        )
        assert synced.status_code == 200, synced.text
        assert client.get("/api/extensions").json() == []
        assert client.get("/api/extensions/catalog").json()["items"] == []

        with SessionLocal() as db:
            extension = db.scalar(
                select(Extension).where(Extension.slug == "internal-search")
            )
            definition = db.scalar(
                select(McpDefinition).where(McpDefinition.slug == "internal-search")
            )
            admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert (
                extension is not None and definition is not None and admin is not None
            )
            assert extension.kind == "mcp"
            version = db.get(ExtensionVersion, extension.latest_published_version_id)
            assert version is not None
            assert version.manifest_json["classification"] == "mcp"
            assert version.manifest_json["mcpSlug"] == "internal-search"
            installation = install_definition(
                db,
                user=admin,
                definition_id=definition.id,
                revision_id=definition.current_revision_id,
                scope_type="user",
                scope_id=admin.id,
                enabled=True,
                tool_allowlist=["search_docs"],
            )
            old_revision_id = installation.configuration_revision_id
            installation_id = installation.id
            db.commit()
            snapshot = resolve_mcp_snapshot(db, user=admin, project_id=project_id)[0]
            assert snapshot["skill_wrapper"]["extension_id"] == extension.id
            assert "반드시 MCP 검색 결과만" in snapshot["skill_wrapper"]["instructions"]
        manifest = json.loads(
            (mcp_root / "internal-search.json").read_text(encoding="utf-8")
        )
        manifest["mcpServers"]["internal-search"]["tools"][0]["description"] = (
            "updated repository schema"
        )
        (mcp_root / "internal-search.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        upgraded = client.post(
            "/api/extensions/repository-sync",
            headers={"X-CSRF-Token": csrf},
        )
        assert upgraded.status_code == 200, upgraded.text
        assert upgraded.json()["mcpChanged"] == 1

        with SessionLocal() as db:
            installation = db.get(McpInstallation, installation_id)
            definition = db.scalar(
                select(McpDefinition).where(McpDefinition.slug == "internal-search")
            )
            assert installation is not None and definition is not None
            assert installation.configuration_revision_id != old_revision_id
            assert installation.configuration_revision_id == definition.current_revision_id
            assert installation.tool_allowlist_json == ["search_docs"]
            installation.configuration_revision_id = old_revision_id
            db.commit()

        repaired = client.post(
            "/api/extensions/repository-sync",
            headers={"X-CSRF-Token": csrf},
        )
        assert repaired.status_code == 200, repaired.text
        assert repaired.json()["mcpChanged"] == 0

        with SessionLocal() as db:
            installation = db.get(McpInstallation, installation_id)
            definition = db.scalar(
                select(McpDefinition).where(McpDefinition.slug == "internal-search")
            )
            assert installation is not None and definition is not None
            assert installation.configuration_revision_id == definition.current_revision_id


def test_selected_mcp_wrapper_guidance_enters_the_run_context(tmp_path: Path) -> None:
    app, settings = _test_app(tmp_path)
    with TestClient(app) as client:
        csrf = _login(client)
        _task, scheduled = _create_manual_scheduled_run(
            client,
            csrf=csrf,
            name="MCP wrapper Context 점검",
            idempotency_key="mcp-wrapper-context-0001",
            max_attempts=1,
        )

    with SessionLocal() as db:
        run = db.get(Run, str(scheduled["runId"]))
        assert run is not None
        run.snapshot_json = {
            **run.snapshot_json,
            "mcp_servers": [
                {
                    "name": "Internal Search",
                    "skill_wrapper": {
                        "digest": "wrapper-digest-v1",
                        "instructions": "승인된 MCP 검색 결과만 근거로 사용합니다.",
                    },
                }
            ],
        }
        run_id = run.id
        db.commit()

    messages = LocalRunExecutor(settings)._conversation_messages(
        run_id, "사내 규정을 찾아주세요."
    )
    assert "Selected MCP guidance: Internal Search" in messages[0].content
    assert "승인된 MCP 검색 결과만 근거로 사용합니다." in messages[0].content


def test_repository_watcher_accepts_supported_extension_paths(tmp_path: Path) -> None:
    extensions_root = tmp_path / "extensions"

    for relative_path in (
        "skills/explorer-added/SKILL.md",
        "mcp/explorer-added.json",
        "plugins/explorer-added/.codex-plugin/plugin.json",
    ):
        assert repository_catalog._is_repository_catalog_path(
            str(extensions_root / relative_path), root=extensions_root
        )

    for relative_path in (
        "skills/explorer-added/node_modules/package.json",
        "mcp/.temporary.json",
        "unrelated/file.txt",
    ):
        assert not repository_catalog._is_repository_catalog_path(
            str(extensions_root / relative_path), root=extensions_root
        )


def test_repository_watcher_detects_explorer_style_file_addition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = tmp_path / "repository"
    skills_root = repository_root / "extensions" / "skills"
    skills_root.mkdir(parents=True)
    synchronized = Event()
    monkeypatch.setattr(
        repository_catalog,
        "_sync_repository_catalog_for_all_organizations",
        lambda _root: synchronized.set(),
    )

    async def exercise_watcher() -> None:
        watcher = asyncio.create_task(
            repository_catalog.watch_repository_catalog(repository_root)
        )
        try:
            await asyncio.sleep(0.1)
            skill_root = skills_root / "explorer-added"
            skill_root.mkdir()
            (skill_root / "SKILL.md").write_text("# Explorer Added\n", encoding="utf-8")
            detected = await asyncio.wait_for(
                asyncio.to_thread(synchronized.wait), timeout=5
            )
            assert detected
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher

    asyncio.run(exercise_watcher())


def test_skill_draft_compare_and_swap_rejects_stale_session(tmp_path: Path) -> None:
    app, _settings = _test_app(tmp_path)
    with TestClient(app) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            "/api/extensions",
            headers={"X-CSRF-Token": csrf},
            json={
                "name": "CAS Skill",
                "slug": "cas-skill",
                "projectId": project_id,
                "package": {"files": {"SKILL.md": "# CAS base"}},
            },
        )
        assert created.status_code == 201, created.text
        draft_payload = created.json()["draft"]
        draft_id = draft_payload["id"]
        initial_digest = draft_payload["digest"]
        listed = next(
            item for item in client.get("/api/extensions").json()
            if item["id"] == created.json()["id"]
        )
        assert "package" not in listed["draft"]
        full_draft = client.get(f"/api/extensions/{created.json()['id']}/draft")
        assert full_draft.status_code == 200, full_draft.text
        initial_skill_md = full_draft.json()["package"]["files"]["SKILL.md"]
        assert "name: cas-skill" in initial_skill_md
        assert initial_skill_md.endswith("# CAS base")

        with SessionLocal() as first_db, SessionLocal() as stale_db:
            first_user = first_db.scalar(
                select(User).where(User.login_id == "admin@posco.com")
            )
            stale_user = stale_db.scalar(
                select(User).where(User.login_id == "admin@posco.com")
            )
            stale_draft = stale_db.get(ExtensionDraft, draft_id)
            assert first_user is not None and stale_user is not None
            assert stale_draft is not None
            assert stale_draft.current_revision == 1

            winner, changed = update_draft(
                first_db,
                user=first_user,
                draft_id=draft_id,
                expected_revision=1,
                expected_digest=initial_digest,
                package_files={"SKILL.md": "# CAS winner"},
                change_summary="winner",
            )
            first_db.commit()
            assert changed is True
            assert winner.current_revision == 2

            with pytest.raises(ApiProblem) as conflict:
                update_draft(
                    stale_db,
                    user=stale_user,
                    draft_id=draft_id,
                    expected_revision=1,
                    expected_digest=initial_digest,
                    package_files={"SKILL.md": "# CAS stale writer"},
                    change_summary="stale",
                )
            assert conflict.value.code == "draft_conflict"

        with SessionLocal() as db:
            persisted = db.get(ExtensionDraft, draft_id)
            revisions = list(
                db.scalars(
                    select(ExtensionDraftRevision)
                    .where(ExtensionDraftRevision.draft_id == draft_id)
                    .order_by(ExtensionDraftRevision.revision_number)
                )
            )
            assert persisted is not None
            assert persisted.current_revision == 2
            persisted_skill_md = persisted.package_json["SKILL.md"]
            assert "name: cas-skill" in persisted_skill_md
            assert persisted_skill_md.endswith("# CAS winner")
            assert [revision.revision_number for revision in revisions] == [1, 2]


def test_skill_version_save_rejects_stale_base_pointer(tmp_path: Path) -> None:
    app, _settings = _test_app(tmp_path)
    with TestClient(app) as client:
        csrf = _login(client)
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            "/api/extensions",
            headers={"X-CSRF-Token": csrf},
            json={
                "name": "Version CAS Skill",
                "slug": "version-cas-skill",
                "projectId": project_id,
                "package": {"files": {"SKILL.md": "# Version CAS"}},
            },
        )
        assert created.status_code == 201, created.text
        draft_payload = created.json()["draft"]
        draft_id = draft_payload["id"]
        digest = draft_payload["digest"]

        with SessionLocal() as first_db, SessionLocal() as stale_db:
            first_user = first_db.scalar(
                select(User).where(User.login_id == "admin@posco.com")
            )
            stale_user = stale_db.scalar(
                select(User).where(User.login_id == "admin@posco.com")
            )
            stale_draft = stale_db.get(ExtensionDraft, draft_id)
            assert first_user is not None and stale_user is not None
            assert stale_draft is not None
            assert stale_draft.base_version_id is None

            winner = save_draft_version(
                first_db,
                user=first_user,
                draft_id=draft_id,
                expected_revision=1,
                expected_digest=digest,
                base_version_id=None,
                manifest={"category": "cas"},
            )
            first_db.commit()
            assert winner.version_number == 1

            with pytest.raises(ApiProblem) as conflict:
                save_draft_version(
                    stale_db,
                    user=stale_user,
                    draft_id=draft_id,
                    expected_revision=1,
                    expected_digest=digest,
                    base_version_id=None,
                    manifest={"category": "stale"},
                )
            assert conflict.value.code == "base_version_conflict"

        with SessionLocal() as db:
            persisted = db.get(ExtensionDraft, draft_id)
            versions = list(
                db.scalars(
                    select(ExtensionVersion)
                    .where(ExtensionVersion.extension_id == created.json()["id"])
                    .order_by(ExtensionVersion.version_number)
                )
            )
            assert persisted is not None
            assert persisted.base_version_id == winner.id
            assert [version.version_number for version in versions] == [1]
            assert versions[0].parent_version_id is None


def test_skill_draft_versions_installation_and_folder_move(tmp_path: Path) -> None:
    app, _settings = _test_app(tmp_path)
    with SessionLocal() as db:
        organization = db.scalar(select(Organization))
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert organization is not None and admin is not None
        create_user(
            db,
            login_name="worker",
            password="pw",
            organization_id=organization.id,
            created_by_user_id=admin.id,
        )
        db.commit()

    with TestClient(app) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            "/api/extensions",
            headers=headers,
            json={
                "name": "점검 보고서 작성",
                "slug": "inspection-report",
                "description": "설비 점검 보고서를 작성합니다.",
                "projectId": project_id,
                "package": {
                    "files": {"SKILL.md": "# 점검 보고서\n\n초기 절차를 따릅니다."}
                },
            },
        )
        assert created.status_code == 201, created.text
        skill = created.json()
        assert skill["visibility"] == "private"
        assert skill["versions"] == []
        draft = skill["draft"]
        assert draft["revision"] == 1
        skill_id = skill["id"]
        draft_id = draft["id"]

        updated = client.patch(
            f"/api/skill-drafts/{draft_id}",
            headers=headers,
            json={
                "expectedRevision": 1,
                "expectedDigest": draft["digest"],
                "package": {
                    "files": {
                        "SKILL.md": "# 점검 보고서\n\n표와 위험도 요약을 포함합니다."
                    }
                },
                "changeSummary": "표와 위험도 추가",
            },
        )
        assert updated.status_code == 200, updated.text
        draft2 = updated.json()
        assert draft2["revision"] == 2

        stale = client.patch(
            f"/api/skill-drafts/{draft_id}",
            headers=headers,
            json={
                "expectedRevision": 1,
                "expectedDigest": draft["digest"],
                "package": {"files": {"SKILL.md": "# 오래된 수정"}},
            },
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "draft_conflict"

        saved_v1 = client.post(
            f"/api/skill-drafts/{draft_id}/save-version",
            headers=headers,
            json={
                "expectedRevision": 2,
                "expectedDigest": draft2["digest"],
                "baseVersionId": None,
                "manifest": {"category": "maintenance"},
            },
        )
        assert saved_v1.status_code == 201, saved_v1.text
        v1 = saved_v1.json()
        assert v1["version"] == 1

        draft3_response = client.patch(
            f"/api/skill-drafts/{draft_id}",
            headers=headers,
            json={
                "expectedRevision": 2,
                "expectedDigest": draft2["digest"],
                "package": {
                    "files": {
                        "SKILL.md": "# 점검 보고서\n\n표, 위험도와 조치 우선순위를 포함합니다."
                    }
                },
                "changeSummary": "우선순위 추가",
            },
        )
        assert draft3_response.status_code == 200
        draft3 = draft3_response.json()
        assert draft3["baseVersion"] == 1
        assert draft3["dirty"] is True
        saved_v2 = client.post(
            f"/api/skill-drafts/{draft_id}/save-version",
            headers=headers,
            json={
                "expectedRevision": 3,
                "expectedDigest": draft3["digest"],
                "baseVersionId": v1["id"],
                "manifest": {"category": "maintenance"},
            },
        )
        assert saved_v2.status_code == 201
        v2 = saved_v2.json()
        assert v2["version"] == 2
        assert v2["parentVersionId"] == v1["id"]

        original_v1 = client.get(f"/api/extension-versions/{v1['id']}")
        assert original_v1.status_code == 200
        assert original_v1.json()["digest"] == v1["digest"]
        assert "우선순위" not in original_v1.json()["package"]["files"]["SKILL.md"]

        folder = client.post(
            "/api/skill-folders",
            headers=headers,
            json={"scopeType": "user", "name": "설비 관리"},
        )
        assert folder.status_code == 201, folder.text
        for invalid_patch in ({}, {"name": None}, {"sortOrder": None}):
            rejected_patch = client.patch(
                f"/api/skill-folders/{folder.json()['id']}",
                headers=headers,
                json=invalid_patch,
            )
            assert rejected_patch.status_code == 422, (
                invalid_patch,
                rejected_patch.text,
            )
        child_folder = client.post(
            "/api/skill-folders",
            headers=headers,
            json={
                "scopeType": "user",
                "parentFolderId": folder.json()["id"],
                "name": "월간 점검",
            },
        )
        assert child_folder.status_code == 201
        cycle = client.post(
            f"/api/skill-folders/{folder.json()['id']}/move",
            headers=headers,
            json={"parentFolderId": child_folder.json()["id"]},
        )
        assert cycle.status_code == 409
        assert cycle.json()["code"] == "folder_cycle"
        moved = client.post(
            f"/api/skills/{skill_id}/move-folder",
            headers=headers,
            json={
                "folderId": folder.json()["id"],
                "scopeType": "user",
            },
        )
        assert moved.status_code == 200, moved.text

        after_move = client.get(f"/api/extensions/{skill_id}").json()
        assert after_move["draft"]["digest"] == draft3["digest"]
        assert [item["digest"] for item in after_move["versions"]] == [
            v1["digest"],
            v2["digest"],
        ]

        installed = client.post(
            "/api/extension-installations",
            headers=headers,
            json={"versionId": v1["id"], "scopeType": "user"},
        )
        assert installed.status_code == 201, installed.text
        installation_id = installed.json()["id"]
        assert installed.json()["projectIds"] is None
        projects_before_scope = client.get("/api/projects").json()
        default_project_id = projects_before_scope[0]["id"]
        second_project = client.post(
            "/api/projects",
            headers=headers,
            json={"name": "Skill 제외 프로젝트"},
        )
        assert second_project.status_code == 201, second_project.text
        scoped = client.patch(
            f"/api/extension-installations/{installation_id}",
            headers=headers,
            json={"projectIds": [default_project_id]},
        )
        assert scoped.status_code == 200, scoped.text
        assert scoped.json()["projectIds"] == [default_project_id]
        assert any(
            item["id"] == installation_id
            for item in client.get(
                "/api/extension-installations",
                params={"project_id": default_project_id},
            ).json()
        )
        assert all(
            item["id"] != installation_id
            for item in client.get(
                "/api/extension-installations",
                params={"project_id": second_project.json()["id"]},
            ).json()
        )
        upgraded = client.post(
            "/api/extension-installations",
            headers=headers,
            json={"versionId": v2["id"], "scopeType": "user"},
        )
        assert upgraded.status_code == 201
        assert upgraded.json()["id"] == installation_id
        assert upgraded.json()["versionId"] == v2["id"]
        removed = client.delete(
            f"/api/extension-installations/{installation_id}", headers=headers
        )
        assert removed.status_code == 204

        client.cookies.clear()
        _login(client, "worker", "pw")
        hidden = client.get(f"/api/extensions/{skill_id}")
        assert hidden.status_code == 404

        client.cookies.clear()
        admin_csrf = _login(client)
        published = client.post(
            f"/api/extension-versions/{v2['id']}/publish",
            headers={"X-CSRF-Token": admin_csrf},
            json={},
        )
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "published"

        client.cookies.clear()
        worker_csrf = _login(client, "worker", "pw")
        visible = client.get(f"/api/extensions/{skill_id}")
        assert visible.status_code == 200
        secret_rejected = client.post(
            "/api/extension-installations",
            headers={"X-CSRF-Token": worker_csrf},
            json={
                "versionId": v2["id"],
                "scopeType": "user",
                "settings": {"apiKey": "must-not-be-stored"},
            },
        )
        assert secret_rejected.status_code == 422
        worker_installed = client.post(
            "/api/extension-installations",
            headers={"X-CSRF-Token": worker_csrf},
            json={"versionId": v2["id"], "scopeType": "user"},
        )
        assert worker_installed.status_code == 201, worker_installed.text

    with SessionLocal() as db:
        versions = list(
            db.scalars(
                select(ExtensionVersion)
                .where(ExtensionVersion.extension_id == skill_id)
                .order_by(ExtensionVersion.version_number)
            )
        )
        draft_row = db.scalar(
            select(ExtensionDraft).where(ExtensionDraft.extension_id == skill_id)
        )
        placement = db.scalar(
            select(SkillFolderPlacement).where(
                SkillFolderPlacement.skill_id == skill_id
            )
        )
        installation = db.get(ExtensionInstallation, installation_id)
        audit_actions = set(db.scalars(select(AuditEvent.action)))
        assert draft_row is not None and placement is not None
        assert [item.version_number for item in versions] == [1, 2]
        assert [item.package_digest for item in versions] == [
            v1["digest"],
            v2["digest"],
        ]
        assert installation is not None and installation.removed_at is not None
        assert {
            "extension_created",
            "skill_draft_updated",
            "skill_version_saved",
            "skill_folder_placement_changed",
            "extension_installed",
            "extension_uninstalled",
        } <= audit_actions


def test_skill_catalog_counts_likes_and_protects_uninstalled_packages(
    tmp_path: Path,
) -> None:
    app, _settings = _test_app(tmp_path)
    with SessionLocal() as db:
        organization = db.scalar(select(Organization))
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert organization is not None and admin is not None
        create_user(
            db,
            login_name="catalog-worker",
            password="pw",
            organization_id=organization.id,
            created_by_user_id=admin.id,
        )
        db.commit()

    with TestClient(app) as client:
        admin_csrf = _login(client)
        created = client.post(
            "/api/extensions",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "name": "회의 액션 추출",
                "slug": "meeting-actions",
                "description": "회의록에서 담당자와 마감일을 추출합니다.",
                "package": {
                    "files": {
                        "SKILL.md": "# 회의 액션 추출\n\n담당자와 마감일을 정리합니다."
                    }
                },
            },
        )
        assert created.status_code == 201, created.text
        skill = created.json()
        draft = skill["draft"]
        saved = client.post(
            f"/api/skill-drafts/{draft['id']}/save-version",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "expectedRevision": draft["revision"],
                "expectedDigest": draft["digest"],
                "baseVersionId": None,
                "manifest": {
                    "category": "업무 관리",
                    "tags": ["회의", "액션아이템"],
                },
            },
        )
        assert saved.status_code == 201, saved.text
        version = saved.json()
        published = client.post(
            f"/api/extension-versions/{version['id']}/publish",
            headers={"X-CSRF-Token": admin_csrf},
            json={},
        )
        assert published.status_code == 200, published.text

        client.cookies.clear()
        worker_csrf = _login(client, "catalog-worker", "pw")
        before = client.get(
            "/api/extensions/catalog",
            params={"query": "액션아이템", "category": "업무 관리"},
        )
        assert before.status_code == 200, before.text
        before_item = next(
            item for item in before.json()["items"] if item["id"] == skill["id"]
        )
        assert before_item == {
            "id": skill["id"],
            "name": "회의 액션 추출",
            "description": "회의록에서 담당자와 마감일을 추출합니다.",
            "category": "업무 관리",
            "tags": ["회의", "액션아이템"],
            "latestVersionId": version["id"],
            "installed": False,
            "installationId": None,
            "canInstall": True,
            "installCount": 0,
            "runCount": 0,
            "likeCount": 0,
            "likedByMe": False,
            "updatedAt": before_item["updatedAt"],
        }
        assert client.get(f"/api/extension-versions/{version['id']}").status_code == 404
        blocked_draft = client.post(
            f"/api/extensions/{skill['id']}/draft",
            headers={"X-CSRF-Token": worker_csrf},
        )
        assert blocked_draft.status_code == 404

        liked = client.put(
            f"/api/extensions/{skill['id']}/like",
            headers={"X-CSRF-Token": worker_csrf},
        )
        assert liked.status_code == 200, liked.text
        assert liked.json() == {"liked": True, "likeCount": 1}

        installed = client.post(
            "/api/extension-installations",
            headers={"X-CSRF-Token": worker_csrf},
            json={"versionId": version["id"], "scopeType": "user"},
        )
        assert installed.status_code == 201, installed.text
        installation_id = installed.json()["id"]
        assert client.get(f"/api/extension-versions/{version['id']}").status_code == 200

        with SessionLocal() as db:
            organization = db.scalar(select(Organization))
            admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            project = db.scalar(
                select(Project).where(Project.owner_user_id == admin.id)
            )
            assert (
                organization is not None and admin is not None and project is not None
            )
            conversation = Conversation(
                organization_id=organization.id,
                project_id=project.id,
                owner_user_id=admin.id,
                title="카탈로그 실행 집계",
            )
            db.add(conversation)
            db.flush()
            db.add(
                Run(
                    organization_id=organization.id,
                    project_id=project.id,
                    conversation_id=conversation.id,
                    user_id=admin.id,
                    status="completed",
                    provider_id="mock",
                    model_key="mock-agent",
                    runtime_model_id="mock-agent",
                    model_display_name="Mock Agent",
                    snapshot_json={
                        "extension_application": "explicit_and_auto",
                        "prompt_references": [
                            {"kind": "skill", "reference_id": skill["id"]}
                        ],
                        "auto_selected_skill_ids": [skill["id"]],
                    },
                    usage_json={},
                    started_at=utc_now(),
                    finished_at=utc_now(),
                )
            )
            db.commit()

        after = client.get("/api/extensions/catalog", params={"sort": "runs"})
        assert after.status_code == 200, after.text
        after_item = next(
            item for item in after.json()["items"] if item["id"] == skill["id"]
        )
        assert after_item["installed"] is True
        assert after_item["installationId"] == installation_id
        assert after_item["installCount"] == 1
        assert after_item["runCount"] == 1
        assert after_item["likeCount"] == 1
        assert after_item["likedByMe"] is True

        removed = client.delete(
            f"/api/extension-installations/{installation_id}",
            headers={"X-CSRF-Token": worker_csrf},
        )
        assert removed.status_code == 204
        assert client.get(f"/api/extension-versions/{version['id']}").status_code == 404
        unliked = client.delete(
            f"/api/extensions/{skill['id']}/like",
            headers={"X-CSRF-Token": worker_csrf},
        )
        assert unliked.status_code == 200, unliked.text
        assert unliked.json() == {"liked": False, "likeCount": 0}

        final_item = next(
            item
            for item in client.get("/api/extensions/catalog").json()["items"]
            if item["id"] == skill["id"]
        )
        assert final_item["installed"] is False
        assert final_item["installCount"] == 0
        assert final_item["runCount"] == 1


def test_published_skill_has_isolated_personal_drafts_and_multiple_owners(
    tmp_path: Path,
) -> None:
    app, _settings = _test_app(tmp_path)
    with SessionLocal() as db:
        organization = db.scalar(select(Organization))
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert organization is not None and admin is not None
        worker = create_user(
            db,
            login_name="worker",
            password="pw",
            organization_id=organization.id,
            created_by_user_id=admin.id,
        )
        worker_id = worker.id
        db.commit()

    with TestClient(app) as client:
        admin_csrf = _login(client)
        admin_headers = {"X-CSRF-Token": admin_csrf}
        created = client.post(
            "/api/extensions",
            headers=admin_headers,
            json={
                "name": "공식 보고서",
                "slug": "official-report",
                "description": "공식 보고서를 작성합니다.",
                "package": {"files": {"SKILL.md": "# 공식 보고서\n\n기본 절차"}},
            },
        )
        assert created.status_code == 201, created.text
        skill = created.json()
        owner_draft = skill["draft"]
        saved = client.post(
            f"/api/skill-drafts/{owner_draft['id']}/save-version",
            headers=admin_headers,
            json={
                "expectedRevision": owner_draft["revision"],
                "expectedDigest": owner_draft["digest"],
                "baseVersionId": None,
                "manifest": {},
            },
        )
        assert saved.status_code == 201, saved.text
        published = client.post(
            f"/api/extension-versions/{saved.json()['id']}/publish",
            headers=admin_headers,
            json={},
        )
        assert published.status_code == 200, published.text

        client.cookies.clear()
        worker_csrf = _login(client, "worker", "pw")
        worker_headers = {"X-CSRF-Token": worker_csrf}
        worker_view = client.get(f"/api/extensions/{skill['id']}")
        assert worker_view.status_code == 200
        assert worker_view.json().get("draft") is None
        assert worker_view.json()["canCreateDraft"] is False
        assert worker_view.json()["canEdit"] is False

        installed = client.post(
            "/api/extension-installations",
            headers=worker_headers,
            json={"versionId": saved.json()["id"], "scopeType": "user"},
        )
        assert installed.status_code == 201, installed.text
        assert (
            client.get(f"/api/extensions/{skill['id']}").json()["canCreateDraft"]
            is True
        )
        checkout = client.post(
            f"/api/extensions/{skill['id']}/draft", headers=worker_headers
        )
        assert checkout.status_code == 200, checkout.text
        personal_draft = checkout.json()
        assert personal_draft["id"] != owner_draft["id"]
        changed = client.patch(
            f"/api/skill-drafts/{personal_draft['id']}",
            headers=worker_headers,
            json={
                "expectedRevision": personal_draft["revision"],
                "expectedDigest": personal_draft["digest"],
                "package": {"files": {"SKILL.md": "# 공식 보고서\n\n개인 개선 절차"}},
                "changeSummary": "개인 절차 개선",
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["revision"] == 2

        client.cookies.clear()
        admin_csrf = _login(client)
        admin_headers = {"X-CSRF-Token": admin_csrf}
        owner_view = client.get(f"/api/extensions/{skill['id']}").json()
        assert owner_view["draft"]["id"] == owner_draft["id"]
        assert owner_view["draft"]["revision"] == 1

        ownership_response = client.post(
            f"/api/skills/{skill['id']}/ownerships",
            headers=admin_headers,
            json={"userId": worker_id, "role": "owner"},
        )
        assert ownership_response.status_code == 201, ownership_response.text
        assert {
            item["principalId"] for item in ownership_response.json()["ownerships"]
        } == {
            skill["ownerUserId"],
            worker_id,
        }
        ownership_by_principal = {
            item["principalId"]: item["id"]
            for item in ownership_response.json()["ownerships"]
        }

        primary_owner_rejected = client.delete(
            f"/api/skills/{skill['id']}/ownerships/"
            f"{ownership_by_principal[skill['ownerUserId']]}",
            headers=admin_headers,
        )
        assert primary_owner_rejected.status_code == 409
        assert (
            primary_owner_rejected.json()["code"] == "primary_owner_transfer_required"
        )

        client.cookies.clear()
        _login(client, "worker", "pw")
        promoted_view = client.get(f"/api/extensions/{skill['id']}").json()
        assert promoted_view["canEdit"] is True
        assert promoted_view["currentUserRole"] == "owner"

        client.cookies.clear()
        admin_csrf = _login(client)
        removed = client.delete(
            f"/api/skills/{skill['id']}/ownerships/{ownership_by_principal[worker_id]}",
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert removed.status_code == 204, removed.text

        client.cookies.clear()
        _login(client, "worker", "pw")
        demoted_view = client.get(f"/api/extensions/{skill['id']}").json()
        assert demoted_view["canEdit"] is False
        assert demoted_view["currentUserRole"] is None

    with SessionLocal() as db:
        drafts = list(
            db.scalars(
                select(ExtensionDraft).where(ExtensionDraft.extension_id == skill["id"])
            )
        )
        ownerships = list(
            db.scalars(
                select(SkillOwnership).where(SkillOwnership.skill_id == skill["id"])
            )
        )
        assert {draft.owner_user_id for draft in drafts} == {
            skill["ownerUserId"],
            worker_id,
        }
        assert len(ownerships) == 1
        assert ownerships[0].principal_id == skill["ownerUserId"]
        assert "skill_ownership_removed" in set(db.scalars(select(AuditEvent.action)))


def test_skill_trash_requires_owner_or_admin_and_supports_restore_and_expiry(
    tmp_path: Path,
) -> None:
    app, _settings = _test_app(tmp_path)
    with SessionLocal() as db:
        organization = db.scalar(select(Organization))
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert organization is not None and admin is not None
        owner = create_user(
            db,
            login_name="skill-owner",
            password="pw",
            organization_id=organization.id,
            created_by_user_id=admin.id,
        )
        maintainer = create_user(
            db,
            login_name="skill-maintainer",
            password="pw",
            organization_id=organization.id,
            created_by_user_id=admin.id,
        )
        owner_id = owner.id
        maintainer_id = maintainer.id
        db.commit()

    with TestClient(app) as client:
        owner_csrf = _login(client, "skill-owner", "pw")
        owner_headers = {"X-CSRF-Token": owner_csrf}
        created = client.post(
            "/api/extensions",
            headers=owner_headers,
            json={
                "name": "삭제 권한 점검",
                "slug": "delete-permission-check",
                "description": "삭제 시 활성 상태가 정리되는지 점검합니다.",
                "package": {"files": {"SKILL.md": "# 삭제 권한 점검"}},
            },
        )
        assert created.status_code == 201, created.text
        skill = created.json()
        assert skill["currentUserRole"] == "owner"
        assert skill["canDelete"] is True

        draft = skill["draft"]
        saved = client.post(
            f"/api/skill-drafts/{draft['id']}/save-version",
            headers=owner_headers,
            json={
                "expectedRevision": draft["revision"],
                "expectedDigest": draft["digest"],
                "baseVersionId": None,
                "manifest": {},
            },
        )
        assert saved.status_code == 201, saved.text
        installed = client.post(
            "/api/extension-installations",
            headers=owner_headers,
            json={
                "versionId": saved.json()["id"],
                "scopeType": "user",
                "enabled": True,
                "settings": {},
            },
        )
        assert installed.status_code == 201, installed.text

        client.cookies.clear()
        admin_csrf = _login(client)
        admin_headers = {"X-CSRF-Token": admin_csrf}
        ownership = client.post(
            f"/api/skills/{skill['id']}/ownerships",
            headers=admin_headers,
            json={"userId": maintainer_id, "role": "maintainer"},
        )
        assert ownership.status_code == 201, ownership.text

        client.cookies.clear()
        maintainer_csrf = _login(client, "skill-maintainer", "pw")
        maintainer_headers = {"X-CSRF-Token": maintainer_csrf}
        maintainer_view = client.get(f"/api/extensions/{skill['id']}")
        assert maintainer_view.status_code == 200, maintainer_view.text
        assert maintainer_view.json()["canDelete"] is False
        forbidden = client.delete(
            f"/api/extensions/{skill['id']}", headers=maintainer_headers
        )
        assert forbidden.status_code == 403, forbidden.text
        assert forbidden.json()["code"] == "extension_delete_forbidden"

        client.cookies.clear()
        owner_csrf = _login(client, "skill-owner", "pw")
        deleted = client.delete(
            f"/api/extensions/{skill['id']}",
            headers={"X-CSRF-Token": owner_csrf},
        )
        assert deleted.status_code == 204, deleted.text
        assert client.get(f"/api/extensions/{skill['id']}").status_code == 404
        assert skill["id"] not in {
            item["id"] for item in client.get("/api/extensions").json()
        }
        trashed = client.get("/api/extensions/trash")
        assert trashed.status_code == 200, trashed.text
        trashed_skill = next(
            item for item in trashed.json() if item["id"] == skill["id"]
        )
        assert trashed_skill["archivedAt"] is not None
        assert trashed_skill["purgesAt"] is not None
        assert datetime.fromisoformat(
            trashed_skill["purgesAt"]
        ) - datetime.fromisoformat(trashed_skill["archivedAt"]) == timedelta(days=30)

        with SessionLocal() as db:
            extension = db.get(Extension, skill["id"])
            draft_row = db.get(ExtensionDraft, draft["id"])
            installation = db.get(ExtensionInstallation, installed.json()["id"])
            bindings = list(
                db.scalars(
                    select(ExtensionDraftBinding).where(
                        ExtensionDraftBinding.draft_id == draft["id"]
                    )
                )
            )
            assert extension is not None and extension.archived_at is not None
            assert draft_row is not None and draft_row.status == "active"
            assert installation is not None
            assert installation.enabled is True and installation.removed_at is None
            assert bindings and all(binding.enabled is True for binding in bindings)

        restored = client.post(
            f"/api/extensions/{skill['id']}/restore",
            headers={"X-CSRF-Token": owner_csrf},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["archivedAt"] is None
        assert skill["id"] in {
            item["id"] for item in client.get("/api/extensions").json()
        }
        assert skill["id"] not in {
            item["id"] for item in client.get("/api/extensions/trash").json()
        }

        admin_deletable = client.post(
            "/api/extensions",
            headers={"X-CSRF-Token": owner_csrf},
            json={
                "name": "관리자 삭제 점검",
                "slug": "admin-delete-check",
                "package": {"files": {"SKILL.md": "# 관리자 삭제 점검"}},
            },
        )
        assert admin_deletable.status_code == 201, admin_deletable.text
        client.cookies.clear()
        admin_csrf = _login(client)
        admin_deleted = client.delete(
            f"/api/extensions/{admin_deletable.json()['id']}",
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert admin_deleted.status_code == 204, admin_deleted.text
        expired_skill_id = admin_deletable.json()["id"]

        with SessionLocal() as db:
            expired = db.get(Extension, expired_skill_id)
            assert expired is not None
            expired.archived_at = datetime.now(UTC) - timedelta(days=31)
            db.commit()

        assert client.get("/api/extensions").status_code == 200

    with SessionLocal() as db:
        extension = db.get(Extension, skill["id"])
        assert extension is not None and extension.archived_at is None
        assert db.get(Extension, expired_skill_id) is None
        assert owner_id == extension.owner_user_id
        actions = set(db.scalars(select(AuditEvent.action)))
        assert {"extension_trashed", "extension_restored"} <= actions


def test_skill_version_history_compare_and_revert_style_rollback(
    tmp_path: Path,
) -> None:
    app, _settings = _test_app(tmp_path)
    with SessionLocal() as db:
        organization = db.scalar(select(Organization))
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert organization is not None and admin is not None
        maintainer = create_user(
            db,
            login_name="version-maintainer",
            password="pw",
            organization_id=organization.id,
            created_by_user_id=admin.id,
        )
        maintainer_id = maintainer.id
        db.commit()

    with TestClient(app) as client:
        admin_csrf = _login(client)
        admin_headers = {"X-CSRF-Token": admin_csrf}
        created = client.post(
            "/api/extensions",
            headers=admin_headers,
            json={
                "name": "Versioned report skill",
                "slug": "versioned-report-skill",
                "description": "Exercises immutable skill history.",
                "package": {
                    "files": {
                        "SKILL.md": "# Report\n\nCreate the original report.\n",
                        "scripts/old.py": "print('old')\n",
                    }
                },
            },
        )
        assert created.status_code == 201, created.text
        skill = created.json()
        draft = skill["draft"]
        saved_v1 = client.post(
            f"/api/skill-drafts/{draft['id']}/save-version",
            headers=admin_headers,
            json={
                "expectedRevision": draft["revision"],
                "expectedDigest": draft["digest"],
                "baseVersionId": None,
                "manifest": {},
            },
        )
        assert saved_v1.status_code == 201, saved_v1.text
        v1 = saved_v1.json()
        assert v1["changeType"] == "save"
        assert v1["restoredFromVersionId"] is None
        assert (
            client.post(
                f"/api/extension-versions/{v1['id']}/publish",
                headers=admin_headers,
                json={},
            ).status_code
            == 200
        )

        current_draft = client.get(f"/api/extensions/{skill['id']}/draft").json()
        changed = client.patch(
            f"/api/skill-drafts/{current_draft['id']}",
            headers=admin_headers,
            json={
                "expectedRevision": current_draft["revision"],
                "expectedDigest": current_draft["digest"],
                "package": {
                    "files": {
                        "SKILL.md": "# Report\n\nCreate the safer report.\n",
                        "scripts/new.py": "print('new')\n",
                    }
                },
                "changeSummary": "Use the safer report workflow",
            },
        )
        assert changed.status_code == 200, changed.text
        changed_draft = changed.json()
        saved_v2 = client.post(
            f"/api/skill-drafts/{changed_draft['id']}/save-version",
            headers=admin_headers,
            json={
                "expectedRevision": changed_draft["revision"],
                "expectedDigest": changed_draft["digest"],
                "baseVersionId": v1["id"],
                "manifest": {},
            },
        )
        assert saved_v2.status_code == 201, saved_v2.text
        v2 = saved_v2.json()
        assert v2["changeSummary"] == "Use the safer report workflow"
        assert v2["parentVersionId"] == v1["id"]
        assert (
            client.post(
                f"/api/extension-versions/{v2['id']}/publish",
                headers=admin_headers,
                json={},
            ).status_code
            == 200
        )

        comparison = client.get(
            f"/api/skills/{skill['id']}/compare",
            params={"from_version_id": v1["id"], "to_version_id": v2["id"]},
        )
        assert comparison.status_code == 200, comparison.text
        diff = comparison.json()
        assert diff["summary"] == {"filesChanged": 3, "additions": 2, "deletions": 2}
        assert {item["path"]: item["status"] for item in diff["files"]} == {
            "SKILL.md": "modified",
            "scripts/new.py": "added",
            "scripts/old.py": "deleted",
        }
        skill_diff = next(item for item in diff["files"] if item["path"] == "SKILL.md")
        assert {line["kind"] for line in skill_diff["hunks"][0]["lines"]} >= {
            "add",
            "delete",
        }

        ownership = client.post(
            f"/api/skills/{skill['id']}/ownerships",
            headers=admin_headers,
            json={"userId": maintainer_id, "role": "maintainer"},
        )
        assert ownership.status_code == 201, ownership.text
        client.cookies.clear()
        maintainer_csrf = _login(client, "version-maintainer", "pw")
        forbidden = client.post(
            f"/api/skills/{skill['id']}/rollbacks",
            headers={"X-CSRF-Token": maintainer_csrf},
            json={
                "targetVersionId": v1["id"],
                "expectedCurrentVersionId": v2["id"],
                "changeSummary": "Maintainer should not publish",
            },
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "skill_rollback_forbidden"

        client.cookies.clear()
        admin_csrf = _login(client)
        rollback = client.post(
            f"/api/skills/{skill['id']}/rollbacks",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "targetVersionId": v1["id"],
                "expectedCurrentVersionId": v2["id"],
                "changeSummary": "Restore the proven workflow",
            },
        )
        assert rollback.status_code == 201, rollback.text
        restored = rollback.json()
        assert restored["version"] == 3
        assert restored["changeType"] == "rollback"
        assert restored["changeSummary"] == "Restore the proven workflow"
        assert restored["parentVersionId"] == v2["id"]
        assert restored["restoredFromVersionId"] == v1["id"]
        assert restored["status"] == "published"

        restored_package = client.get(f"/api/extension-versions/{restored['id']}")
        assert restored_package.status_code == 200, restored_package.text
        assert restored_package.json()["package"] == v1["package"]
        refreshed = client.get(f"/api/extensions/{skill['id']}").json()
        assert refreshed["latestPublishedVersionId"] == restored["id"]
        assert [version["version"] for version in refreshed["versions"]] == [1, 2, 3]

        stale = client.post(
            f"/api/skills/{skill['id']}/rollbacks",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "targetVersionId": v2["id"],
                "expectedCurrentVersionId": v2["id"],
                "changeSummary": "Stale restore",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "published_version_conflict"

    with SessionLocal() as db:
        assert "skill_version_rolled_back" in set(db.scalars(select(AuditEvent.action)))


def test_schedule_run_now_enable_disable_and_due_dispatch(tmp_path: Path) -> None:
    app, _settings = _test_app(tmp_path)
    with TestClient(app) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            "/api/scheduled-tasks",
            headers=headers,
            json={
                "projectId": project_id,
                "name": "매일 점검 요약",
                "instructions": "오늘의 설비 점검 결과를 HTML 보고서로 작성해 주세요.",
                "scheduleKind": "daily",
                "scheduleConfig": {"hour": 9, "minute": 30},
                "timezone": "Asia/Seoul",
                "execution": {
                    "providerId": "mock",
                    "modelKey": "mock-agent",
                    "effortId": "medium",
                },
                "extensionSnapshotPolicy": "pinned",
            },
        )
        assert created.status_code == 201, created.text
        task = created.json()
        task_id = task["id"]
        assert task["enabled"] is True
        assert task["nextRunAt"] is not None

        disabled = client.post(
            f"/api/scheduled-tasks/{task_id}/disable", headers=headers
        )
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False
        assert disabled.json()["nextRunAt"] is None
        enabled = client.post(f"/api/scheduled-tasks/{task_id}/enable", headers=headers)
        assert enabled.status_code == 200
        assert enabled.json()["enabled"] is True

        run_now_headers = {**headers, "Idempotency-Key": "manual-run-0001"}
        first = client.post(
            f"/api/scheduled-tasks/{task_id}/run-now", headers=run_now_headers
        )
        assert first.status_code == 202, first.text
        scheduled_run = first.json()
        assert scheduled_run["runId"] is not None
        assert scheduled_run["inputSnapshot"]["scheduled_task_id"] == task_id
        assert scheduled_run["inputSnapshot"]["project_id"] == project_id
        second = client.post(
            f"/api/scheduled-tasks/{task_id}/run-now", headers=run_now_headers
        )
        assert second.status_code == 202
        assert second.json()["id"] == scheduled_run["id"]

        history = client.get(f"/api/scheduled-tasks/{task_id}/runs")
        assert history.status_code == 200
        assert len(history.json()) == 1
        assert history.json()[0]["runId"] == scheduled_run["runId"]

    fixed_now = datetime(2026, 7, 11, 0, 0, tzinfo=UTC)
    with SessionLocal() as db:
        task_row = db.get(ScheduledTask, task_id)
        assert task_row is not None
        task_row.next_run_at = fixed_now - timedelta(minutes=1)
        db.commit()
    with SessionLocal() as db:
        due = dispatch_due_tasks(db, now=fixed_now)
        assert len(due) == 1
        due_run_id = due[0].run_id
        db.commit()
    with SessionLocal() as db:
        repeated = dispatch_due_tasks(db, now=fixed_now)
        assert repeated == []
        linked_run = db.get(Run, due_run_id)
        assert linked_run is not None
        assert linked_run.project_id == project_id
        assert linked_run.snapshot_json["scheduled_task_id"] == task_id
        assert linked_run.snapshot_json["extensions"] == []
        scheduled_rows = list(
            db.scalars(
                select(ScheduledRun).where(ScheduledRun.scheduled_task_id == task_id)
            )
        )
        assert len(scheduled_rows) == 2


def test_schedule_patch_rejects_empty_and_null_non_nullable_fields(
    tmp_path: Path,
) -> None:
    app, _settings = _test_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            "/api/scheduled-tasks",
            headers=headers,
            json={
                "projectId": project_id,
                "name": "예약 수정 검증",
                "instructions": "예약 수정 입력을 검증합니다.",
                "scheduleKind": "daily",
                "scheduleConfig": {"hour": 9, "minute": 30},
                "timezone": "Asia/Seoul",
            },
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]

        invalid_patches = [
            {},
            {"projectId": None},
            {"name": None},
            {"instructions": None},
            {"scheduleKind": None},
            {"scheduleConfig": None},
            {"timezone": None},
            {"contextMode": None},
            {"execution": None},
            {"extensionSnapshotPolicy": None},
            {"deliveryPolicy": None},
            {"maxAttempts": None},
            {"timeoutSeconds": None},
        ]
        for patch in invalid_patches:
            response = client.patch(
                f"/api/scheduled-tasks/{task_id}", headers=headers, json=patch
            )
            assert response.status_code == 422, (patch, response.text)

        unchanged = client.get(f"/api/scheduled-tasks/{task_id}")
        assert unchanged.status_code == 200
        assert unchanged.json()["name"] == "예약 수정 검증"
        assert unchanged.json()["scheduleConfig"] == {"hour": 9, "minute": 30}


def test_schedule_patch_updates_project_timing_and_execution(tmp_path: Path) -> None:
    app, _settings = _test_app(tmp_path)
    with TestClient(app) as client:
        csrf = _login(client)
        headers = {"X-CSRF-Token": csrf}
        projects = client.get("/api/projects").json()
        source_project_id = projects[0]["id"]
        destination = client.post(
            "/api/projects",
            headers=headers,
            json={"name": "예약 결과 프로젝트"},
        )
        assert destination.status_code == 201, destination.text
        destination_project_id = destination.json()["id"]
        created = client.post(
            "/api/scheduled-tasks",
            headers=headers,
            json={
                "projectId": source_project_id,
                "name": "예약 수정 전",
                "instructions": "수정 전 지시사항",
                "scheduleKind": "daily",
                "scheduleConfig": {"hour": 9, "minute": 30},
            },
        )
        assert created.status_code == 201, created.text

        updated = client.patch(
            f"/api/scheduled-tasks/{created.json()['id']}",
            headers=headers,
            json={
                "projectId": destination_project_id,
                "name": "예약 수정 후",
                "instructions": "수정 후 지시사항",
                "scheduleKind": "weekly",
                "scheduleConfig": {"weekday": 4, "hour": 18, "minute": 45},
                "execution": {
                    "providerId": "mock",
                    "modelKey": "mock-agent",
                    "effortId": "high",
                },
            },
        )
        assert updated.status_code == 200, updated.text
        payload = updated.json()
        assert payload["projectId"] == destination_project_id
        assert payload["name"] == "예약 수정 후"
        assert payload["instructions"] == "수정 후 지시사항"
        assert payload["scheduleKind"] == "weekly"
        assert payload["scheduleConfig"] == {
            "weekday": 4,
            "hour": 18,
            "minute": 45,
        }
        assert payload["execution"] == {
            "providerId": "mock",
            "modelKey": "mock-agent",
            "effortId": "high",
        }
        assert client.get(
            "/api/scheduled-tasks", params={"project_id": source_project_id}
        ).json() == []
        destination_tasks = client.get(
            "/api/scheduled-tasks", params={"project_id": destination_project_id}
        ).json()
        assert [task["id"] for task in destination_tasks] == [payload["id"]]


def test_scheduled_run_recovers_idempotency_conflict_after_stale_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _settings = _test_app(tmp_path)
    with TestClient(app) as client:
        csrf = _login(client)
        task_payload, scheduled_payload = _create_manual_scheduled_run(
            client,
            csrf=csrf,
            name="동시 예약 충돌 복구",
            idempotency_key="schedule-race-0001",
            max_attempts=1,
        )

    with SessionLocal() as db:
        task = db.get(ScheduledTask, str(task_payload["id"]))
        scheduled_run = db.get(ScheduledRun, str(scheduled_payload["id"]))
        assert task is not None and scheduled_run is not None
        owner = db.get(User, task.owner_user_id)
        assert owner is not None
        run_count = len(list(db.scalars(select(Run.id))))
        conversation_count = len(list(db.scalars(select(Conversation.id))))

        real_scalar = db.scalar
        stale_lookup_returned = False

        def scalar_with_stale_first_lookup(*args: object, **kwargs: object) -> object:
            nonlocal stale_lookup_returned
            if not stale_lookup_returned:
                stale_lookup_returned = True
                return None
            return real_scalar(*args, **kwargs)

        monkeypatch.setattr(db, "scalar", scalar_with_stale_first_lookup)
        recovered, created = start_scheduled_run(
            db,
            user=owner,
            task=task,
            trigger_type="manual",
            scheduled_for=scheduled_run.scheduled_for,
            idempotency_key=scheduled_run.idempotency_key,
        )

        assert stale_lookup_returned is True
        assert created is False
        assert recovered.id == scheduled_run.id
        assert len(list(db.scalars(select(Run.id)))) == run_count
        assert len(list(db.scalars(select(Conversation.id)))) == conversation_count


def test_scheduled_run_syncs_terminal_artifacts_and_in_app_delivery(
    tmp_path: Path,
) -> None:
    app, _settings = _test_app(tmp_path)
    with TestClient(app) as client:
        csrf = _login(client)
        task, scheduled = _create_manual_scheduled_run(
            client,
            csrf=csrf,
            name="완료 결과 동기화",
            idempotency_key="terminal-sync-0001",
            max_attempts=1,
        )
        assert scheduled["inputSnapshot"]["delivery_policy"]["in_app"] is True
        completed_at = datetime.now(UTC)
        with SessionLocal() as db:
            run = db.get(Run, str(scheduled["runId"]))
            assert run is not None
            run.status = "completed"
            run.started_at = completed_at - timedelta(seconds=2)
            run.finished_at = completed_at
            artifact = Artifact(
                organization_id=run.organization_id,
                project_id=run.project_id,
                conversation_id=run.conversation_id,
                source_run_id=run.id,
                created_by_user_id=run.user_id,
                display_name="설비 점검 결과.html",
                kind="html",
                mime_type="text/html",
                visibility="private",
            )
            db.add(artifact)
            db.commit()
            artifact_id = artifact.id

        history = client.get(f"/api/scheduled-tasks/{task['id']}/runs")
        assert history.status_code == 200, history.text
        result = history.json()[0]
        assert result["status"] == "completed"
        assert result["outputArtifactIds"] == [artifact_id]
        assert result["error"] is None
        assert result["delivery"] == {
            "channel": "in_app",
            "status": "available",
            "outputArtifactIds": [artifact_id],
            "completedAt": completed_at.isoformat().replace("+00:00", "Z"),
        }


def test_scheduled_run_uses_frozen_skill_snapshot_as_model_selected_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen_extensions = [
        {
            "extension_id": "skill-frozen-inspection",
            "kind": "skill",
            "slug": "frozen-inspection",
            "name": "동결 점검 절차",
            "source": "version",
            "version_id": "version-1",
            "version": 1,
            "digest": "frozen-digest-v1",
            "instructions": "반드시 동결된 점검 절차 v1을 적용합니다.",
        }
    ]
    monkeypatch.setattr(
        schedules_service,
        "_execution_extension_snapshot",
        lambda _db, _task, _user: frozen_extensions,
    )
    app, settings = _test_app(tmp_path)
    with TestClient(app) as client:
        csrf = _login(client)
        _task, scheduled = _create_manual_scheduled_run(
            client,
            csrf=csrf,
            name="동결 Skill 실행",
            idempotency_key="frozen-skill-0001",
            max_attempts=2,
        )

    with SessionLocal() as db:
        run = db.get(Run, str(scheduled["runId"]))
        assert run is not None
        snapshot = run.snapshot_json
        assert snapshot["extensions"] == frozen_extensions
        assert snapshot["extension_application"] == "snapshot_candidates"
        stable_prefix = {
            "contract_version": snapshot["contract_version"],
            "agent": snapshot["agent"],
            "project": snapshot["project"],
            "execution": snapshot["execution"],
            "output_mode": snapshot["output_mode"],
            "analysis_depth": snapshot["analysis_depth"],
            "answer_length": snapshot["answer_length"],
            "instructions": snapshot["instructions"],
            "runtime_prompts": snapshot["runtime_prompts"],
            "extensions": frozen_extensions,
            "extension_application": "snapshot_candidates",
            "environment_type": snapshot["environment_type"],
            "approval_mode": snapshot["approval_mode"],
            "clarification_mode": snapshot["clarification_mode"],
            "prompt_cache_scope": snapshot["prompt_cache_scope"],
        }
        expected_hash = hashlib.sha256(
            json.dumps(
                stable_prefix,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        assert snapshot["prompt_prefix_hash"] == expected_hash
        run_id = run.id

    messages = LocalRunExecutor(settings)._conversation_messages(
        run_id, "점검 보고서를 작성해 주세요."
    )
    assert "Scheduled Skill snapshot:" not in messages[0].content
    assert "Selected Skill:" not in messages[0].content
    assert "반드시 동결된 점검 절차 v1을 적용합니다." not in messages[0].content

    interrupted_at = datetime.now(UTC)
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        scheduled_row = db.get(ScheduledRun, str(scheduled["id"]))
        assert run is not None and scheduled_row is not None
        run.status = "interrupted"
        run.finished_at = interrupted_at
        scheduled_row.status = "running"
        db.commit()
    with SessionLocal() as db:
        enqueue_ids, notify_ids = maintain_scheduled_runs(
            db, now=interrupted_at + timedelta(seconds=5)
        )
        assert notify_ids == []
        assert len(enqueue_ids) == 1
        retry_run = db.get(Run, enqueue_ids[0])
        assert retry_run is not None
        assert retry_run.snapshot_json["extensions"] == frozen_extensions
        assert retry_run.snapshot_json["extension_application"] == "snapshot_candidates"
        assert retry_run.snapshot_json["prompt_prefix_hash"] == expected_hash
        retry_run_id = retry_run.id
        db.commit()

    retry_messages = LocalRunExecutor(settings)._conversation_messages(
        retry_run_id, "점검 보고서를 다시 작성해 주세요."
    )
    assert "Scheduled Skill snapshot:" not in retry_messages[0].content
    assert "Selected Skill:" not in retry_messages[0].content
    assert "반드시 동결된 점검 절차 v1을 적용합니다." not in retry_messages[0].content


def test_scheduled_timeout_retries_once_and_duplicate_ticks_do_not_dispatch_twice(
    tmp_path: Path,
) -> None:
    app, _settings = _test_app(tmp_path)
    with TestClient(app) as client:
        csrf = _login(client)
        _task, scheduled = _create_manual_scheduled_run(
            client,
            csrf=csrf,
            name="timeout 재시도",
            idempotency_key="timeout-retry-0001",
            max_attempts=2,
        )

    scheduled_run_id = str(scheduled["id"])
    first_run_id = str(scheduled["runId"])
    snapshot = scheduled["inputSnapshot"]
    timed_out_at = datetime.now(UTC)
    with SessionLocal() as db:
        first_run = db.get(Run, first_run_id)
        assert first_run is not None
        first_run.queued_at = timed_out_at - timedelta(seconds=31)
        db.commit()

    with SessionLocal() as db:
        enqueue_ids, notify_ids = maintain_scheduled_runs(db, now=timed_out_at)
        assert enqueue_ids == []
        assert notify_ids == [first_run_id]
        scheduled_row = db.get(ScheduledRun, scheduled_run_id)
        first_run = db.get(Run, first_run_id)
        assert scheduled_row is not None and first_run is not None
        assert scheduled_row.status == "retry_waiting"
        assert scheduled_row.attempt == 1
        assert first_run.status == "cancelled"
        assert first_run.error_code == "scheduled_timeout"
        assert (
            len(
                list(
                    db.scalars(
                        select(RunCommand).where(RunCommand.run_id == first_run_id)
                    )
                )
            )
            == 1
        )
        db.commit()

    # A duplicate tick after commit neither emits another cancel command nor dispatches.
    with SessionLocal() as db:
        assert maintain_scheduled_runs(db, now=timed_out_at) == ([], [])
        assert (
            len(
                list(
                    db.scalars(
                        select(RunCommand).where(RunCommand.run_id == first_run_id)
                    )
                )
            )
            == 1
        )
        db.commit()

    retry_at = timed_out_at + timedelta(seconds=5)
    with SessionLocal() as db:
        enqueue_ids, notify_ids = maintain_scheduled_runs(db, now=retry_at)
        assert notify_ids == []
        assert len(enqueue_ids) == 1
        retry_run_id = enqueue_ids[0]
        scheduled_row = db.get(ScheduledRun, scheduled_run_id)
        retry_run = db.get(Run, retry_run_id)
        assert scheduled_row is not None and retry_run is not None
        assert scheduled_row.status == "queued"
        assert scheduled_row.attempt == 2
        assert scheduled_row.run_id == retry_run_id
        assert scheduled_row.input_snapshot_json == snapshot
        assert retry_run.parent_run_id == first_run_id
        assert retry_run.snapshot_json["scheduled_attempt"] == 2
        assert retry_run.snapshot_json["extensions"] == snapshot["extensions"]
        db.commit()

    # A new DB session represents a restart/second scheduler tick over persisted state.
    with SessionLocal() as db:
        assert maintain_scheduled_runs(db, now=retry_at) == ([], [])
        assert len(list(db.scalars(select(Run)))) == 2
        retry_run = db.get(Run, retry_run_id)
        assert retry_run is not None
        retry_run.status = "failed"
        retry_run.started_at = retry_at
        retry_run.finished_at = retry_at + timedelta(seconds=1)
        retry_run.error_code = "provider_request"
        retry_run.error_message = "Provider 요청이 실패했습니다."
        db.commit()

    with SessionLocal() as db:
        assert maintain_scheduled_runs(db, now=retry_at + timedelta(seconds=10)) == (
            [],
            [],
        )
        scheduled_row = db.get(ScheduledRun, scheduled_run_id)
        assert scheduled_row is not None
        assert scheduled_row.status == "failed"
        assert scheduled_row.attempt == 2
        assert scheduled_row.error_code == "provider_request"
        assert scheduled_run_payload(scheduled_row)["delivery"]["status"] == "failed"
        assert len(list(db.scalars(select(Run)))) == 2


def test_interrupted_scheduled_run_retries_once_after_restart(tmp_path: Path) -> None:
    app, _settings = _test_app(tmp_path)
    with TestClient(app) as client:
        csrf = _login(client)
        _task, scheduled = _create_manual_scheduled_run(
            client,
            csrf=csrf,
            name="재시작 복구",
            idempotency_key="restart-retry-0001",
            max_attempts=2,
        )

    scheduled_run_id = str(scheduled["id"])
    first_run_id = str(scheduled["runId"])
    interrupted_at = datetime.now(UTC)
    with SessionLocal() as db:
        scheduled_row = db.get(ScheduledRun, scheduled_run_id)
        run = db.get(Run, first_run_id)
        assert scheduled_row is not None and run is not None
        scheduled_row.status = "running"
        run.status = "interrupted"
        run.started_at = interrupted_at - timedelta(seconds=3)
        run.finished_at = interrupted_at
        db.commit()

    with SessionLocal() as db:
        enqueue_ids, notify_ids = maintain_scheduled_runs(
            db, now=interrupted_at + timedelta(seconds=5)
        )
        assert notify_ids == []
        assert len(enqueue_ids) == 1
        retry_run_id = enqueue_ids[0]
        db.commit()

    with SessionLocal() as db:
        assert maintain_scheduled_runs(
            db, now=interrupted_at + timedelta(seconds=5)
        ) == ([], [])
        scheduled_row = db.get(ScheduledRun, scheduled_run_id)
        retry_run = db.get(Run, retry_run_id)
        assert scheduled_row is not None and retry_run is not None
        assert scheduled_row.attempt == 2
        assert scheduled_row.run_id == retry_run_id
        assert retry_run.parent_run_id == first_run_id
        assert len(list(db.scalars(select(Run)))) == 2


def test_next_occurrence_respects_timezone_and_weekdays() -> None:
    friday_after_work = datetime(2026, 7, 10, 10, 0, tzinfo=UTC)  # 19:00 KST
    result = next_occurrence(
        kind="weekdays",
        config={"hour": 9, "minute": 0},
        timezone="Asia/Seoul",
        after=friday_after_work,
    )
    assert result == datetime(2026, 7, 13, 0, 0, tzinfo=UTC)


def test_skill_tags_are_editable_by_skill_maintainers(tmp_path: Path) -> None:
    app, _settings = _test_app(tmp_path)
    with SessionLocal() as db:
        organization = db.scalar(select(Organization))
        admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert organization is not None and admin is not None
        maintainer = create_user(
            db,
            login_name="tag-maintainer",
            password="pw",
            organization_id=organization.id,
            created_by_user_id=admin.id,
        )
        maintainer_id = maintainer.id
        db.commit()

    with TestClient(app) as client:
        admin_csrf = _login(client)
        admin_headers = {"X-CSRF-Token": admin_csrf}
        created = client.post(
            "/api/extensions",
            headers=admin_headers,
            json={
                "name": "태그 권한 Skill",
                "description": "태그 권한 확인",
                "package": {"files": {"SKILL.md": "# 태그 권한 Skill"}},
            },
        )
        assert created.status_code == 201, created.text
        skill = created.json()
        assert skill["canEditTags"] is True

        ownership = client.post(
            f"/api/skills/{skill['id']}/ownerships",
            headers=admin_headers,
            json={"userId": maintainer_id, "role": "maintainer"},
        )
        assert ownership.status_code == 201, ownership.text

        client.cookies.clear()
        maintainer_csrf = _login(client, "tag-maintainer", "pw")
        maintainer_view = client.get(f"/api/extensions/{skill['id']}").json()
        assert maintainer_view["canEdit"] is True
        assert maintainer_view["canEditTags"] is True
        updated = client.patch(
            f"/api/extensions/{skill['id']}",
            headers={"X-CSRF-Token": maintainer_csrf},
            json={
                "name": skill["name"],
                "description": skill["description"],
                "tags": ["Agent", "개발", "#Agent"],
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["tags"] == ["Agent", "개발"]

        client.cookies.clear()
        _login(client)
        catalog_item = next(
            item
            for item in client.get("/api/extensions/catalog").json()["items"]
            if item["id"] == skill["id"]
        )
        assert catalog_item["tags"] == ["Agent", "개발"]
