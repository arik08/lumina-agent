from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select

from lumina.agent.executor import LocalRunExecutor
from lumina.auth import create_user
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.migrations import SERVER_ROOT, upgrade_database
from lumina.models import (
    AuditEvent,
    Organization,
    ProjectMembership,
    Run,
    User,
    UserMemory,
)
from lumina.project_memories.service import EMPTY_HASH


def _settings(tmp_path: Path, name: str = "project-memory.db") -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
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


def _completed_run(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    *,
    text: str,
    suffix: str,
) -> str:
    conversation = client.post(
        "/api/conversations",
        headers=headers,
        json={"projectId": project_id, "title": f"학습 출처 {suffix}"},
    )
    assert conversation.status_code == 201, conversation.text
    started = client.post(
        f"/api/conversations/{conversation.json()['id']}/runs",
        headers={**headers, "Idempotency-Key": f"project-learning-{suffix}"},
        json={
            "message": {"text": text, "attachmentIds": [], "promptReferences": []},
            "execution": {
                "providerId": "mock",
                "modelKey": "mock-agent",
                "effortId": "medium",
            },
        },
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["run"]["runId"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/runs/{run_id}/snapshot")
        assert snapshot.status_code == 200
        if snapshot.json()["status"] == "completed":
            return run_id
        time.sleep(0.03)
    raise AssertionError("source Run did not complete")


def _proposal(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    *,
    run_id: str,
    target_type: str,
    target_id: str | None,
    base_revision: int,
    base_hash: str,
    patch: dict[str, object],
    rationale: str = "반복 업무에 필요한 검증된 기준입니다.",
):
    return client.post(
        f"/api/projects/{project_id}/learning-proposals",
        headers=headers,
        json={
            "sourceRunIds": [run_id],
            "targetType": target_type,
            "targetId": target_id,
            "baseRevision": base_revision,
            "baseHash": base_hash,
            "proposedPatch": patch,
            "rationale": rationale,
            "evidenceRefs": [{"kind": "run", "referenceId": run_id}],
            "expectedScope": "project",
        },
    )


def _approve_apply(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    proposal_id: str,
) -> dict[str, Any]:
    approved = client.post(
        f"/api/projects/{project_id}/learning-proposals/{proposal_id}/approve",
        headers=headers,
        json={"note": "Project 범위 적용을 승인합니다."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    applied = client.post(
        f"/api/projects/{project_id}/learning-proposals/{proposal_id}/apply",
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["proposal"]["status"] == "applied"
    return applied.json()


@pytest.mark.parametrize(
    "sensitive_text",
    (
        "비밀번호: super-secret-1234",
        "개인 계정 owner@example.com을 사용합니다.",
        "이번만 승인해서 보안 정책을 우회합니다.",
    ),
)
def test_project_learning_rejects_sensitive_content(
    tmp_path: Path, sensitive_text: str
) -> None:
    settings = _settings(tmp_path, f"sensitive-{abs(hash(sensitive_text))}.db")
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project = client.get("/api/projects").json()[0]
        run_id = _completed_run(
            client,
            headers,
            project["id"],
            text="안전한 Project 기준을 검토합니다.",
            suffix=str(abs(hash(sensitive_text))),
        )
        rejected = _proposal(
            client,
            headers,
            project["id"],
            run_id=run_id,
            target_type="project_memory",
            target_id=None,
            base_revision=0,
            base_hash=EMPTY_HASH,
            patch={
                "category": "project_rule",
                "fact": sensitive_text,
                "displayText": sensitive_text,
            },
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] in {
            "sensitive_memory_forbidden",
            "sensitive_project_learning_forbidden",
        }


def test_project_memory_revision_snapshot_delete_and_rollback(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = _login(client)
        project = client.get("/api/projects").json()[0]
        project_id = project["id"]
        source_run_id = _completed_run(
            client,
            headers,
            project_id,
            text="베어링 점검 기준을 Project에 제안합니다.",
            suffix="memory-source",
        )

        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert admin is not None
            db.add(
                UserMemory(
                    user_id=admin.id,
                    category="communication_preference",
                    normalized_fact="private user preference",
                    display_text="개인 UserMemory",
                    source_message_ids_json=[],
                    source_run_ids_json=[source_run_id],
                    confidence=1.0,
                    evidence_count=1,
                    status="active",
                )
            )
            db.commit()
        assert client.get(f"/api/projects/{project_id}/memories").json() == []

        created = _proposal(
            client,
            headers,
            project_id,
            run_id=source_run_id,
            target_type="project_memory",
            target_id=None,
            base_revision=0,
            base_hash=EMPTY_HASH,
            patch={
                "category": "project_rule",
                "fact": "bearing inspection interval: quarterly",
                "displayText": "베어링 점검 주기는 분기 1회입니다.",
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["evidenceRefs"] == [
            {
                "kind": "run",
                "referenceId": source_run_id,
                "versionOrDigest": None,
                "note": "",
            }
        ]
        assert "reference_id" not in created.json()["evidenceRefs"][0]
        first_apply = _approve_apply(client, headers, project_id, created.json()["id"])
        memory_v1 = first_apply["projectMemory"]
        assert memory_v1["revision"] == 1

        snapshotted_run_id = _completed_run(
            client,
            headers,
            project_id,
            text="베어링 점검 주기를 알려 주세요.",
            suffix="memory-snapshot",
        )
        with SessionLocal() as db:
            snapshotted_run = db.get(Run, snapshotted_run_id)
            assert snapshotted_run is not None
            snapshots = snapshotted_run.snapshot_json["project_memories"]
            assert snapshots[0]["id"] == memory_v1["id"]
            assert snapshots[0]["revision"] == 1
            assert snapshots[0]["content_hash"] == memory_v1["contentHash"]
            user_snapshots = snapshotted_run.snapshot_json["user_memories"]
            assert user_snapshots == []
        prompt_messages = LocalRunExecutor(settings)._conversation_messages(
            snapshotted_run_id,
            "베어링 점검 주기를 알려 주세요.",
        )
        assert any(
            message.role == "system"
            and f"project_memory_id={memory_v1['id']}" in str(message.content)
            and "revision=1" in str(message.content)
            and "개인 UserMemory" not in str(message.content)
            for message in prompt_messages
        )
        assert any(
            message.role == "user"
            and message.content == "베어링 점검 주기를 알려 주세요."
            and not (
                f"project_memory_id={memory_v1['id']}" in str(message.content)
                or "개인 UserMemory" in str(message.content)
            )
            for message in prompt_messages
        )

        unrelated_run_id = _completed_run(
            client,
            headers,
            project_id,
            text="출장 일정을 알려 주세요.",
            suffix="memory-unrelated",
        )
        with SessionLocal() as db:
            unrelated_run = db.get(Run, unrelated_run_id)
            assert unrelated_run is not None
            assert unrelated_run.snapshot_json["user_memories"] == []
            assert unrelated_run.snapshot_json["project_memories"] == []

        updated = _proposal(
            client,
            headers,
            project_id,
            run_id=source_run_id,
            target_type="project_memory",
            target_id=memory_v1["memoryKey"],
            base_revision=1,
            base_hash=memory_v1["contentHash"],
            patch={"displayText": "베어링 점검 주기는 매월 1회입니다."},
        )
        assert updated.status_code == 201, updated.text
        second_apply = _approve_apply(client, headers, project_id, updated.json()["id"])
        memory_v2 = second_apply["projectMemory"]
        assert memory_v2["revision"] == 2

        with SessionLocal() as db:
            unchanged_run = db.get(Run, snapshotted_run_id)
            assert unchanged_run is not None
            assert unchanged_run.snapshot_json["project_memories"][0]["revision"] == 1

        deletion = _proposal(
            client,
            headers,
            project_id,
            run_id=source_run_id,
            target_type="project_memory",
            target_id=memory_v2["memoryKey"],
            base_revision=2,
            base_hash=memory_v2["contentHash"],
            patch={"delete": True},
            rationale="더 이상 사용하지 않는 Project 기준입니다.",
        )
        assert deletion.status_code == 201, deletion.text
        deleted_apply = _approve_apply(
            client, headers, project_id, deletion.json()["id"]
        )
        assert deleted_apply["projectMemory"]["status"] == "deleted"
        assert client.get(f"/api/projects/{project_id}/memories").json() == []

        rolled_back = client.post(
            f"/api/projects/{project_id}/learning-proposals/{deletion.json()['id']}/rollback",
            headers=headers,
        )
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["proposal"]["status"] == "rolled_back"
        restored = rolled_back.json()["projectMemory"]
        assert restored["revision"] == 4
        assert restored["displayText"] == memory_v2["displayText"]

        history = client.get(
            f"/api/projects/{project_id}/memories/{memory_v1['memoryKey']}"
        )
        assert history.status_code == 200
        assert [item["revision"] for item in history.json()["revisions"]] == [
            4,
            3,
            2,
            1,
        ]
        assert [item["status"] for item in history.json()["revisions"]] == [
            "active",
            "rolled_back",
            "superseded",
            "superseded",
        ]

    with SessionLocal() as db:
        actions = {
            event.action
            for event in db.scalars(
                select(AuditEvent).where(
                    AuditEvent.target_type == "project_learning_proposal"
                )
            )
        }
        assert {
            "project_learning_proposed",
            "project_learning_approved",
            "project_learning_applied",
            "project_learning_rolled_back",
        } <= actions


def test_project_concept_permissions_stale_isolation_apply_and_rollback(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, "concept.db")
    with TestClient(create_app(settings)) as client:
        admin_headers = _login(client)
        project = client.get("/api/projects").json()[0]
        project_id = project["id"]
        source_run_id = _completed_run(
            client,
            admin_headers,
            project_id,
            text="Project concept 개선을 검토합니다.",
            suffix="concept-source",
        )
        other_project = client.post(
            "/api/projects",
            headers=admin_headers,
            json={"name": "비공개 Project", "description": ""},
        ).json()

        with SessionLocal() as db:
            organization = db.scalar(select(Organization))
            admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            assert organization is not None and admin is not None
            member = create_user(
                db,
                login_name="project-member",
                password="member-password",
                organization_id=organization.id,
                created_by_user_id=admin.id,
            )
            db.add(
                ProjectMembership(
                    project_id=project_id,
                    user_id=member.id,
                    role="member",
                    status="active",
                    created_by_user_id=admin.id,
                )
            )
            db.commit()

        member_headers = _login(client, "project-member", "member-password")
        isolated = client.get(f"/api/projects/{other_project['id']}/learning-proposals")
        assert isolated.status_code == 404

        member_proposal = _proposal(
            client,
            member_headers,
            project_id,
            run_id=source_run_id,
            target_type="project_concept",
            target_id=None,
            base_revision=project["conceptRevision"],
            base_hash=project["conceptHash"],
            patch={"concept": "승인 전 Project concept"},
        )
        assert member_proposal.status_code == 201, member_proposal.text
        forbidden = client.post(
            f"/api/projects/{project_id}/learning-proposals/{member_proposal.json()['id']}/approve",
            headers=member_headers,
        )
        assert forbidden.status_code == 403

        admin_headers = _login(client)
        changed = client.patch(
            f"/api/projects/{project_id}",
            headers=admin_headers,
            json={"concept": "관리자가 먼저 변경한 concept"},
        )
        assert changed.status_code == 200
        stale = client.post(
            f"/api/projects/{project_id}/learning-proposals/{member_proposal.json()['id']}/approve",
            headers=admin_headers,
        )
        assert stale.status_code == 200
        assert stale.json()["status"] == "stale"

        current_project = next(
            item
            for item in client.get("/api/projects").json()
            if item["id"] == project_id
        )
        concept_proposal = _proposal(
            client,
            admin_headers,
            project_id,
            run_id=source_run_id,
            target_type="project_concept",
            target_id=None,
            base_revision=current_project["conceptRevision"],
            base_hash=current_project["conceptHash"],
            patch={"concept": "승인되어 적용된 Project concept"},
        )
        assert concept_proposal.status_code == 201
        applied = _approve_apply(
            client, admin_headers, project_id, concept_proposal.json()["id"]
        )
        assert applied["projectMemory"] is None
        applied_project = next(
            item
            for item in client.get("/api/projects").json()
            if item["id"] == project_id
        )
        assert applied_project["concept"] == "승인되어 적용된 Project concept"
        assert (
            applied_project["conceptRevision"] == current_project["conceptRevision"] + 1
        )

        snapshotted_run_id = _completed_run(
            client,
            admin_headers,
            project_id,
            text="현재 Project concept로 답변합니다.",
            suffix="concept-snapshot",
        )
        rolled_back = client.post(
            f"/api/projects/{project_id}/learning-proposals/{concept_proposal.json()['id']}/rollback",
            headers=admin_headers,
        )
        assert rolled_back.status_code == 200
        assert rolled_back.json()["proposal"]["status"] == "rolled_back"
        restored_project = next(
            item
            for item in client.get("/api/projects").json()
            if item["id"] == project_id
        )
        assert restored_project["concept"] == current_project["concept"]
        assert (
            restored_project["conceptRevision"]
            == applied_project["conceptRevision"] + 1
        )
        with SessionLocal() as db:
            snapshotted = db.get(Run, snapshotted_run_id)
            assert snapshotted is not None
            assert snapshotted.snapshot_json["project"]["concept"] == (
                "승인되어 적용된 Project concept"
            )
            assert (
                snapshotted.snapshot_json["project"]["concept_revision"]
                == (applied_project["conceptRevision"])
            )


def test_project_memory_migration_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "project-memory-migration.db"
    database_url = f"sqlite:///{database.as_posix()}"
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    upgrade_database(database_url)
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert {"project_memories", "project_learning_proposals"} <= set(
            inspector.get_table_names()
        )
        project_columns = {
            column["name"] for column in inspector.get_columns("projects")
        }
        assert {"concept_revision", "concept_hash"} <= project_columns
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision()
                == expected_head
            )
    finally:
        engine.dispose()

    config.attributes["database_url"] = database_url
    command.downgrade(config, "0007")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert {"project_memories", "project_learning_proposals"}.isdisjoint(
            inspector.get_table_names()
        )
        project_columns = {
            column["name"] for column in inspector.get_columns("projects")
        }
        assert {"concept_revision", "concept_hash"}.isdisjoint(project_columns)
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision()
                == expected_head
            )
    finally:
        engine.dispose()
