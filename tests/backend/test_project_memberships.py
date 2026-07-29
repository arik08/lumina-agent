from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lumina.auth.service import create_user
from lumina.config import Settings
from lumina.db import SessionLocal
from lumina.main import create_app
from lumina.models import AuditEvent, Organization, Project, ProjectMembership, User


def _settings(tmp_path: Path, name: str) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _login(
    client: TestClient,
    login_name: str,
    password: str = "password",
    *,
    domain: str = "posco.com",
) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={
            "loginName": login_name,
            "loginDomain": domain,
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrfToken"]}


def _create_posco_user(
    login_name: str, *, status: str = "active", role: str = "user"
) -> dict[str, str]:
    with SessionLocal() as db:
        organization_id = db.scalar(
            select(Organization.id).where(Organization.slug == "posco")
        )
        assert organization_id is not None
        user = create_user(
            db,
            login_name=login_name,
            password="password",
            organization_id=organization_id,
            display_name=login_name.replace("-", " ").title(),
            role=role,
            status=status,
        )
        db.commit()
        return {"id": user.id, "loginId": user.login_id}


def _default_project(client: TestClient) -> dict[str, object]:
    response = client.get("/api/projects")
    assert response.status_code == 200, response.text
    return next(item for item in response.json() if item["isDefault"])


def test_memberships_toggle_project_between_personal_and_shared(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, "membership-project-scope.db"))
    with TestClient(app) as client:
        _create_posco_user("scope-owner")
        collaborator = _create_posco_user("scope-collaborator")
        headers = _login(client, "scope-owner")
        project = _default_project(client)
        project_id = str(project["id"])
        assert project["projectType"] == "personal"

        added = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=headers,
            json={"loginId": collaborator["loginId"], "role": "member"},
        )
        assert added.status_code == 201, added.text
        shared_project = next(
            item for item in client.get("/api/projects").json() if item["id"] == project_id
        )
        assert shared_project["projectType"] == "shared"
        with SessionLocal() as db:
            persisted_project = db.get(Project, project_id)
            assert persisted_project is not None
            assert persisted_project.visibility == "shared"

        revoked = client.delete(
            f"/api/projects/{project_id}/memberships/{added.json()['id']}",
            headers=headers,
            params={"expectedRole": "member", "expectedStatus": "active"},
        )
        assert revoked.status_code == 204, revoked.text
        personal_project = next(
            item for item in client.get("/api/projects").json() if item["id"] == project_id
        )
        assert personal_project["projectType"] == "personal"
        with SessionLocal() as db:
            persisted_project = db.get(Project, project_id)
            assert persisted_project is not None
            assert persisted_project.visibility == "private"


def test_project_membership_lifecycle_permissions_and_audit(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, "membership-lifecycle.db"))
    with TestClient(app) as client:
        owner = _create_posco_user("project-owner")
        member = _create_posco_user("project-member")
        viewer = _create_posco_user("project-viewer")
        candidate = _create_posco_user("project-candidate")
        inactive = _create_posco_user("inactive-member", status="disabled")

        owner_headers = _login(client, "project-owner")
        project = _default_project(client)
        project_id = str(project["id"])
        assert project["role"] == "owner"

        owner_membership = next(
            item
            for item in client.get(f"/api/projects/{project_id}/memberships").json()
            if item["userId"] == owner["id"]
        )

        missing_identity = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=owner_headers,
            json={"role": "member"},
        )
        assert missing_identity.status_code == 422
        both_identities = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=owner_headers,
            json={
                "userId": member["id"],
                "loginId": member["loginId"],
                "role": "member",
            },
        )
        assert both_identities.status_code == 422

        added_member = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=owner_headers,
            json={"loginId": member["loginId"], "role": "member"},
        )
        assert added_member.status_code == 201, added_member.text
        member_membership = added_member.json()
        assert set(member_membership) == {
            "id",
            "projectId",
            "userId",
            "loginId",
            "displayName",
            "accountStatus",
            "role",
            "status",
            "isProjectOwner",
            "createdByUserId",
            "createdAt",
            "updatedAt",
        }
        assert member_membership["role"] == "member"
        assert "password" not in added_member.text.lower()
        assert "token" not in added_member.text.lower()

        idempotent = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=owner_headers,
            json={"userId": member["id"], "role": "member"},
        )
        assert idempotent.status_code == 200, idempotent.text
        assert idempotent.json()["id"] == member_membership["id"]

        added_viewer = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=owner_headers,
            json={"userId": viewer["id"], "role": "viewer"},
        )
        assert added_viewer.status_code == 201, added_viewer.text
        viewer_membership = added_viewer.json()

        inactive_add = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=owner_headers,
            json={"userId": inactive["id"], "role": "member"},
        )
        assert inactive_add.status_code == 409
        assert inactive_add.json()["code"] == "organization_user_inactive"

        member_headers = _login(client, "project-member")
        member_listing = client.get(f"/api/projects/{project_id}/memberships")
        assert member_listing.status_code == 200
        member_project = next(
            item
            for item in client.get("/api/projects").json()
            if item["id"] == project_id
        )
        assert member_project["role"] == "member"
        assert member_project["projectType"] == "shared"
        member_cannot_manage = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=member_headers,
            json={"userId": candidate["id"], "role": "member"},
        )
        assert member_cannot_manage.status_code == 403
        assert (
            member_cannot_manage.json()["code"] == "project_membership_manager_required"
        )

        viewer_headers = _login(client, "project-viewer")
        viewer_project = next(
            item
            for item in client.get("/api/projects").json()
            if item["id"] == project_id
        )
        assert viewer_project["role"] == "viewer"
        viewer_cannot_manage = client.patch(
            f"/api/projects/{project_id}/memberships/{viewer_membership['id']}",
            headers=viewer_headers,
            json={
                "role": "member",
                "expectedRole": "viewer",
                "expectedStatus": "active",
            },
        )
        assert viewer_cannot_manage.status_code == 403

        owner_headers = _login(client, "project-owner")
        promoted = client.patch(
            f"/api/projects/{project_id}/memberships/{member_membership['id']}",
            headers=owner_headers,
            json={
                "role": "admin",
                "expectedRole": "member",
                "expectedStatus": "active",
            },
        )
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["role"] == "admin"

        stale = client.patch(
            f"/api/projects/{project_id}/memberships/{member_membership['id']}",
            headers=owner_headers,
            json={
                "role": "viewer",
                "expectedRole": "member",
                "expectedStatus": "active",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "project_membership_conflict"
        assert stale.json()["details"] == {
            "currentRole": "admin",
            "currentStatus": "active",
        }

        project_admin_headers = _login(client, "project-member")
        admin_added = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=project_admin_headers,
            json={"userId": candidate["id"], "role": "member"},
        )
        assert admin_added.status_code == 201, admin_added.text

        owner_headers = _login(client, "project-owner")
        revoked = client.delete(
            f"/api/projects/{project_id}/memberships/{viewer_membership['id']}",
            headers=owner_headers,
            params={"expectedRole": "viewer", "expectedStatus": "active"},
        )
        assert revoked.status_code == 204, revoked.text
        active_only = client.get(
            f"/api/projects/{project_id}/memberships",
            params={"includeRevoked": "false"},
        )
        assert viewer["id"] not in {item["userId"] for item in active_only.json()}
        with_revoked = client.get(f"/api/projects/{project_id}/memberships")
        assert (
            next(
                item for item in with_revoked.json() if item["userId"] == viewer["id"]
            )["status"]
            == "revoked"
        )

        _login(client, "project-viewer")
        lost_access = client.get(f"/api/projects/{project_id}/memberships")
        assert lost_access.status_code == 404

        owner_headers = _login(client, "project-owner")
        reactivated = client.patch(
            f"/api/projects/{project_id}/memberships/{viewer_membership['id']}",
            headers=owner_headers,
            json={
                "status": "active",
                "expectedRole": "viewer",
                "expectedStatus": "revoked",
            },
        )
        assert reactivated.status_code == 200, reactivated.text
        assert reactivated.json()["status"] == "active"

        with SessionLocal() as db:
            events = list(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.target_type == "project_membership",
                        AuditEvent.metadata_json["project_id"].as_string()
                        == project_id,
                    )
                )
            )
        actions = {event.action for event in events}
        assert {
            "project_membership_added",
            "project_membership_confirmed",
            "project_membership_changed",
            "project_membership_revoked",
        } <= actions
        assert any(
            event.action == "project_membership_added"
            and event.actor_user_id == member["id"]
            for event in events
        )
        audit_json = json.dumps(
            [event.metadata_json for event in events], default=str
        ).lower()
        assert "password" not in audit_json
        assert "token" not in audit_json
        assert owner_membership["role"] == "owner"


def test_project_owner_guards_and_nested_membership_isolation(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, "membership-owner-guards.db"))
    with TestClient(app) as client:
        owner = _create_posco_user("guard-owner")
        second_owner = _create_posco_user("guard-second-owner")
        headers = _login(client, "guard-owner")
        default_project = _default_project(client)
        default_project_id = str(default_project["id"])
        default_owner_membership = next(
            item
            for item in client.get(
                f"/api/projects/{default_project_id}/memberships"
            ).json()
            if item["userId"] == owner["id"]
        )

        protected_patch = client.patch(
            "/api/projects/"
            f"{default_project_id}/memberships/{default_owner_membership['id']}",
            headers=headers,
            json={
                "role": "admin",
                "expectedRole": "owner",
                "expectedStatus": "active",
            },
        )
        assert protected_patch.status_code == 409
        assert protected_patch.json()["code"] == "default_project_owner_protected"
        protected_delete = client.delete(
            "/api/projects/"
            f"{default_project_id}/memberships/{default_owner_membership['id']}",
            headers=headers,
            params={"expectedRole": "owner", "expectedStatus": "active"},
        )
        assert protected_delete.status_code == 409
        assert protected_delete.json()["code"] == "default_project_owner_protected"

        created_project = client.post(
            "/api/projects",
            headers=headers,
            json={"name": "Shared maintenance", "description": "owner guard test"},
        )
        assert created_project.status_code == 201, created_project.text
        project_id = created_project.json()["id"]
        original_membership = next(
            item
            for item in client.get(f"/api/projects/{project_id}/memberships").json()
            if item["userId"] == owner["id"]
        )
        added_second_owner = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=headers,
            json={"userId": second_owner["id"], "role": "owner"},
        )
        assert added_second_owner.status_code == 201, added_second_owner.text
        second_membership = added_second_owner.json()

        nested_mismatch = client.patch(
            f"/api/projects/{project_id}/memberships/{default_owner_membership['id']}",
            headers=headers,
            json={
                "role": "member",
                "expectedRole": "owner",
                "expectedStatus": "active",
            },
        )
        assert nested_mismatch.status_code == 404
        assert nested_mismatch.json()["code"] == "project_membership_not_found"

        protected_original = client.patch(
            f"/api/projects/{project_id}/memberships/{original_membership['id']}",
            headers=headers,
            json={
                "role": "member",
                "expectedRole": "owner",
                "expectedStatus": "active",
            },
        )
        assert protected_original.status_code == 409
        assert protected_original.json()["code"] == "project_owner_protected"
        still_owner = next(
            item
            for item in client.get("/api/projects").json()
            if item["id"] == project_id
        )
        assert still_owner["role"] == "owner"
        still_owner_membership = next(
            item
            for item in client.get(f"/api/projects/{project_id}/memberships").json()
            if item["id"] == original_membership["id"]
        )
        assert still_owner_membership["role"] == "owner"

        # Guard legacy/imported data where the canonical owner's membership is
        # already inconsistent, leaving the additional owner as the sole active one.
        with SessionLocal() as db:
            legacy_owner_membership = db.get(
                ProjectMembership, original_membership["id"]
            )
            assert legacy_owner_membership is not None
            legacy_owner_membership.role = "admin"
            db.commit()

        last_owner_delete = client.delete(
            f"/api/projects/{project_id}/memberships/{second_membership['id']}",
            headers=headers,
            params={"expectedRole": "owner", "expectedStatus": "active"},
        )
        assert last_owner_delete.status_code == 409
        assert last_owner_delete.json()["code"] == "last_project_owner_required"
        last_owner_demote = client.patch(
            f"/api/projects/{project_id}/memberships/{second_membership['id']}",
            headers=headers,
            json={
                "role": "admin",
                "expectedRole": "owner",
                "expectedStatus": "active",
            },
        )
        assert last_owner_demote.status_code == 409
        assert last_owner_demote.json()["code"] == "last_project_owner_required"


def test_admin_membership_management_is_limited_to_its_organization(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path, "membership-organization.db"))
    with TestClient(app) as client:
        owner = _create_posco_user("organization-owner")
        target = _create_posco_user("organization-target")
        owner_headers = _login(client, "organization-owner")
        project_id = str(_default_project(client)["id"])

        with SessionLocal() as db:
            other_organization = Organization(slug="other-org", name="Other Org")
            db.add(other_organization)
            db.flush()
            other_admin = create_user(
                db,
                login_name="other-admin",
                login_domain="other.example",
                password="password",
                organization_id=other_organization.id,
                display_name="Other Admin",
                role="admin",
            )
            db.commit()
            other_admin_id = other_admin.id

        other_org_add = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=owner_headers,
            json={"userId": other_admin_id, "role": "member"},
        )
        assert other_org_add.status_code == 404
        assert other_org_add.json()["code"] == "organization_user_not_found"

        admin_headers = _login(client, "admin", "1111")
        same_org_admin_add = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=admin_headers,
            json={"userId": target["id"], "role": "viewer"},
        )
        assert same_org_admin_add.status_code == 201, same_org_admin_add.text
        assert same_org_admin_add.json()["role"] == "viewer"

        other_admin_headers = _login(client, "other-admin", domain="other.example")
        other_projects = client.get("/api/projects")
        assert other_projects.status_code == 200
        assert project_id not in {item["id"] for item in other_projects.json()}
        direct_read = client.get(f"/api/projects/{project_id}/memberships")
        assert direct_read.status_code == 404
        direct_manage = client.post(
            f"/api/projects/{project_id}/memberships",
            headers=other_admin_headers,
            json={"userId": owner["id"], "role": "member"},
        )
        assert direct_manage.status_code == 404

        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
            audit = db.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "project_membership_added",
                    AuditEvent.target_id == same_org_admin_add.json()["id"],
                )
            )
        assert admin is not None
        assert audit is not None
        assert audit.actor_user_id == admin.id
        assert audit.organization_id == admin.organization_id
