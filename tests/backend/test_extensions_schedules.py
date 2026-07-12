from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.api.errors import install_error_handlers
from lumina.api.routes import auth, extensions, projects, schedules
from lumina.agent.executor import LocalRunExecutor
from lumina.auth import bootstrap_database, create_user
from lumina.config import Settings, get_settings
from lumina.db import SessionLocal, configure_database, create_schema
from lumina.models import (
    Artifact,
    AuditEvent,
    ExtensionDraft,
    ExtensionInstallation,
    ExtensionVersion,
    Organization,
    Run,
    RunCommand,
    ScheduledRun,
    ScheduledTask,
    SkillFolderPlacement,
    SkillOwnership,
    User,
)
from lumina.schedules.service import (
    dispatch_due_tasks,
    maintain_scheduled_runs,
    next_occurrence,
    scheduled_run_payload,
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


def _login(client: TestClient, name: str = "admin", password: str = "1") -> str:
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
        assert worker_view.json()["canCreateDraft"] is True
        assert worker_view.json()["canEdit"] is False

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
        assert primary_owner_rejected.json()["code"] == "primary_owner_transfer_required"

        client.cookies.clear()
        _login(client, "worker", "pw")
        promoted_view = client.get(f"/api/extensions/{skill['id']}").json()
        assert promoted_view["canEdit"] is True
        assert promoted_view["currentUserRole"] == "owner"

        client.cookies.clear()
        admin_csrf = _login(client)
        removed = client.delete(
            f"/api/skills/{skill['id']}/ownerships/"
            f"{ownership_by_principal[worker_id]}",
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
        assert linked_run.snapshot_json["scheduled_task_id"] == task_id
        assert linked_run.snapshot_json["extensions"] == []
        scheduled_rows = list(
            db.scalars(
                select(ScheduledRun).where(ScheduledRun.scheduled_task_id == task_id)
            )
        )
        assert len(scheduled_rows) == 2


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


def test_scheduled_run_applies_frozen_skill_snapshot_to_hash_and_prompt(
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
        assert snapshot["extension_application"] == "all_snapshot"
        stable_prefix = {
            "contract_version": snapshot["contract_version"],
            "agent": snapshot["agent"],
            "project": snapshot["project"],
            "execution": snapshot["execution"],
            "output_mode": snapshot["output_mode"],
            "instructions": snapshot["instructions"],
            "extensions": frozen_extensions,
            "extension_application": "all_snapshot",
            "environment_type": snapshot["environment_type"],
            "approval_mode": snapshot["approval_mode"],
            "prompt_cache_key": snapshot["prompt_cache_key"],
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
    assert "Scheduled Skill snapshot: 동결 점검 절차" in messages[0].content
    assert "반드시 동결된 점검 절차 v1을 적용합니다." in messages[0].content

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
        assert retry_run.snapshot_json["extension_application"] == "all_snapshot"
        assert retry_run.snapshot_json["prompt_prefix_hash"] == expected_hash
        retry_run_id = retry_run.id
        db.commit()

    retry_messages = LocalRunExecutor(settings)._conversation_messages(
        retry_run_id, "점검 보고서를 다시 작성해 주세요."
    )
    assert "Scheduled Skill snapshot: 동결 점검 절차" in retry_messages[0].content
    assert "반드시 동결된 점검 절차 v1을 적용합니다." in retry_messages[0].content


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
