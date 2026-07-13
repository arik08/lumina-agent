from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.instructions.service import (
    InstructionSnapshot,
    InstructionScope,
    instruction_digest,
    resolve_instruction_stack,
)
from lumina.main import create_app
from lumina.models import AuditEvent, Run


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'instructions.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _login(client: TestClient, login_name: str, password: str) -> dict[str, str]:
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


def _create_user(client: TestClient, csrf: str, login_name: str) -> dict[str, object]:
    response = client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": csrf},
        json={
            "loginName": login_name,
            "loginDomain": "posco.com",
            "password": "test-password",
            "role": "user",
            "status": "active",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _patch_payload(document: dict[str, object], content: str) -> dict[str, object]:
    return {
        "content": content,
        "expectedRevision": document["revision"],
        "expectedDigest": document["digest"],
    }


def test_instruction_api_permissions_concurrency_and_secret_guard(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        admin_headers = _login(client, "admin", "1")

        organization = client.get("/api/admin/organization/instructions")
        assert organization.status_code == 200, organization.text
        assert organization.headers["cache-control"] == "no-store"
        assert organization.json()["scope"] == "organization"
        updated_organization = client.patch(
            "/api/admin/organization/instructions",
            headers=admin_headers,
            json=_patch_payload(
                organization.json(), "모든 결과에는 근거와 검토 상태를 표시합니다."
            ),
        )
        assert updated_organization.status_code == 200, updated_organization.text
        assert updated_organization.json()["revision"] == 2
        labeled_revision = client.patch(
            "/api/admin/organization/instructions/revisions/2/label",
            headers=admin_headers,
            json={"label": "운영 기준"},
        )
        assert labeled_revision.status_code == 200, labeled_revision.text
        assert labeled_revision.json() == {"revision": 2, "label": "운영 기준"}
        assert client.get("/api/admin/organization/instructions").json()[
            "revisionLabels"
        ] == {"2": "운영 기준"}
        edited_history = client.patch(
            "/api/admin/organization/instructions/revisions/1",
            headers=admin_headers,
            json={"content": "수정된 과거 지침"},
        )
        assert edited_history.status_code == 200, edited_history.text
        assert client.get(
            "/api/admin/organization/instructions/revisions/1"
        ).json()["content"] == "수정된 과거 지침"

        owner = _create_user(client, admin_headers["X-CSRF-Token"], "instruction-owner")
        member = _create_user(
            client, admin_headers["X-CSRF-Token"], "instruction-member"
        )
        _create_user(client, admin_headers["X-CSRF-Token"], "instruction-outsider")

        client.cookies.clear()
        owner_headers = _login(client, "instruction-owner", "test-password")
        personal = client.get("/api/instructions/personal")
        assert personal.status_code == 200
        assert personal.json()["appliesToSharedProjects"] is False
        assert "ETag" in personal.headers

        private_marker = "PRIVATE_PERSONAL_MARKER: 답변은 표로 정리합니다."
        updated_personal = client.patch(
            "/api/instructions/personal",
            headers=owner_headers,
            json=_patch_payload(personal.json(), private_marker),
        )
        assert updated_personal.status_code == 200, updated_personal.text
        assert updated_personal.json()["revision"] == 2
        assert updated_personal.json()["digest"] == instruction_digest(private_marker)

        stale = client.patch(
            "/api/instructions/personal",
            headers=owner_headers,
            json=_patch_payload(personal.json(), "오래된 편집"),
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "instruction_conflict"
        assert stale.json()["details"]["currentRevision"] == 2

        secret = client.patch(
            "/api/instructions/personal",
            headers=owner_headers,
            json=_patch_payload(
                updated_personal.json(), "api_key = this-is-a-real-secret-value"
            ),
        )
        assert secret.status_code == 422
        assert secret.json()["code"] == "instruction_secret_rejected"

        projects = client.get("/api/projects").json()
        owner_project = next(item for item in projects if item["isDefault"])
        project_id = owner_project["id"]
        membership = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=owner_headers,
            json={"userId": member["id"], "role": "member"},
        )
        assert membership.status_code == 201, membership.text

        project_document = client.get(f"/api/projects/{project_id}/instructions")
        assert project_document.status_code == 200
        assert project_document.json()["editable"] is True
        updated_project = client.patch(
            f"/api/projects/{project_id}/instructions",
            headers=owner_headers,
            json=_patch_payload(
                project_document.json(), "설비 명칭은 원문 표기를 유지합니다."
            ),
        )
        assert updated_project.status_code == 200, updated_project.text

        conversation = client.post(
            "/api/conversations",
            headers=owner_headers,
            json={"projectId": project_id, "title": "지침 snapshot 검증"},
        )
        assert conversation.status_code == 201, conversation.text
        started = client.post(
            f"/api/conversations/{conversation.json()['id']}/runs",
            headers={
                **owner_headers,
                "Idempotency-Key": "instruction-snapshot-run-0001",
            },
            json={"message": {"text": "지침 적용 상태를 확인해 주세요."}},
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["run"]["runId"]
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            assert run is not None
            pinned = run.snapshot_json["instructions"]
            assert [layer["scope"] for layer in pinned["layers"]] == [
                "organization",
                "agent",
                "project",
                "personal",
            ]
            assert "모든 결과에는 근거와 검토 상태" in pinned["prompt_text"]
            assert "설비 명칭은 원문 표기" in pinned["prompt_text"]
            assert private_marker in pinned["prompt_text"]
            assert all(layer["digest"] for layer in pinned["layers"])

        client.cookies.clear()
        member_headers = _login(client, "instruction-member", "test-password")
        member_view = client.get(f"/api/projects/{project_id}/instructions")
        assert member_view.status_code == 200
        assert member_view.json()["editable"] is True
        assert member_view.json()["content"] == updated_project.json()["content"]
        member_edit = client.patch(
            f"/api/projects/{project_id}/instructions",
            headers=member_headers,
            json=_patch_payload(member_view.json(), "구성원이 직접 관리하는 지침"),
        )
        assert member_edit.status_code == 200, member_edit.text
        assert member_edit.json()["content"] == "구성원이 직접 관리하는 지침"

        member_personal = client.get("/api/instructions/personal")
        assert member_personal.status_code == 200
        assert private_marker not in member_personal.text
        assert private_marker not in client.get("/api/projects").text
        assert client.get("/api/admin/organization/instructions").status_code == 403

        client.cookies.clear()
        _login(client, "instruction-outsider", "test-password")
        assert client.get(f"/api/projects/{project_id}/instructions").status_code == 404

        with SessionLocal() as db:
            events = list(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action.in_(
                            (
                                "organization_instructions_changed",
                                "personal_instructions_changed",
                                "project_instructions_changed",
                            )
                        )
                    )
                )
            )
        assert len(events) == 4
        serialized_audit = json.dumps(
            [event.metadata_json for event in events], ensure_ascii=False
        )
        assert private_marker not in serialized_audit
        assert all(
            set(event.metadata_json) == {"revision", "digest"} for event in events
        )
        assert owner["id"] == updated_personal.json()["scopeId"]


def _snapshot(
    scope: InstructionScope, scope_id: str, content: str
) -> InstructionSnapshot:
    return InstructionSnapshot(
        scope=scope,
        scope_id=scope_id,
        content=content,
        revision=3,
        digest=instruction_digest(content),
        updated_at=None,
    )


def test_instruction_resolver_order_and_shared_project_isolation() -> None:
    organization = _snapshot("organization", "org", "ORGANIZATION_LAYER")
    project = _snapshot("project", "project", "PROJECT_LAYER")
    personal = _snapshot("personal", "user", "PRIVATE_PERSONAL_LAYER")

    personal_stack = resolve_instruction_stack(
        organization=organization,
        project=project,
        personal=personal,
        project_type="personal",
        agent_default="AGENT_LAYER",
    )
    assert [layer.scope for layer in personal_stack.layers] == [
        "organization",
        "agent",
        "project",
        "personal",
    ]
    assert personal_stack.prompt_text.index(
        "ORGANIZATION_LAYER"
    ) < personal_stack.prompt_text.index("AGENT_LAYER")
    assert personal_stack.prompt_text.index(
        "AGENT_LAYER"
    ) < personal_stack.prompt_text.index("PROJECT_LAYER")
    assert personal_stack.prompt_text.index(
        "PROJECT_LAYER"
    ) < personal_stack.prompt_text.index("PRIVATE_PERSONAL_LAYER")

    shared_stack = resolve_instruction_stack(
        organization=organization,
        project=project,
        personal=personal,
        project_type="shared",
        agent_default="AGENT_LAYER",
    )
    assert [layer.scope for layer in shared_stack.layers] == [
        "organization",
        "agent",
        "project",
    ]
    assert shared_stack.excluded_scopes == ("personal",)
    assert "PRIVATE_PERSONAL_LAYER" not in shared_stack.prompt_text
