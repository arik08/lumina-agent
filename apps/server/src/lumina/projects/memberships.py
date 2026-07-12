from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..authorization import require_project
from ..models import Project, ProjectMembership, User, utc_now


PROJECT_ROLES = frozenset({"owner", "admin", "member", "viewer"})
MEMBERSHIP_STATUSES = frozenset({"active", "revoked"})


def require_membership_manager(db: Session, user: User, project_id: str) -> Project:
    project = require_project(db, user, project_id)
    if user.role == "admin" or project.owner_user_id == user.id:
        return project
    manager = db.scalar(
        select(ProjectMembership.id).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.user_id == user.id,
            ProjectMembership.status == "active",
            ProjectMembership.role.in_(("owner", "admin")),
        )
    )
    if manager is None:
        raise ApiProblem(
            403,
            "project_membership_manager_required",
            "Project owner 또는 admin만 구성원을 관리할 수 있습니다.",
        )
    return project


def list_memberships(
    db: Session, *, user: User, project_id: str, include_revoked: bool = True
) -> list[tuple[ProjectMembership, User]]:
    require_project(db, user, project_id)
    statement = (
        select(ProjectMembership, User)
        .join(User, User.id == ProjectMembership.user_id)
        .where(ProjectMembership.project_id == project_id)
    )
    if not include_revoked:
        statement = statement.where(ProjectMembership.status == "active")
    result = db.execute(
        statement.order_by(
            ProjectMembership.status,
            ProjectMembership.role,
            User.login_id,
            ProjectMembership.id,
        )
    )
    return list(result.tuples().all())


def effective_project_role(db: Session, *, user: User, project: Project) -> str:
    if project.owner_user_id == user.id:
        return "owner"
    if user.role == "admin":
        return "admin"
    role = db.scalar(
        select(ProjectMembership.role).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.user_id == user.id,
            ProjectMembership.status == "active",
        )
    )
    if role is None:
        raise ApiProblem(404, "not_found", "Project를 찾을 수 없습니다.")
    return role


def resolve_organization_user(
    db: Session,
    *,
    project: Project,
    user_id: str | None,
    login_id: str | None,
) -> User:
    if user_id is not None:
        target = db.scalar(
            select(User).where(
                User.id == user_id,
                User.organization_id == project.organization_id,
            )
        )
    else:
        normalized_login_id = (login_id or "").strip().casefold()
        target = db.scalar(
            select(User).where(
                User.login_id == normalized_login_id,
                User.organization_id == project.organization_id,
            )
        )
    if target is None:
        raise ApiProblem(
            404,
            "organization_user_not_found",
            "같은 Organization의 사용자를 찾을 수 없습니다.",
        )
    if target.status != "active":
        raise ApiProblem(
            409,
            "organization_user_inactive",
            "비활성 사용자는 Project에 추가할 수 없습니다.",
        )
    return target


def add_membership(
    db: Session,
    *,
    actor: User,
    project_id: str,
    user_id: str | None,
    login_id: str | None,
    role: str,
) -> tuple[ProjectMembership, User, bool]:
    project = require_membership_manager(db, actor, project_id)
    target = resolve_organization_user(
        db, project=project, user_id=user_id, login_id=login_id
    )
    if role not in PROJECT_ROLES:
        raise ApiProblem(
            422, "invalid_project_role", "Project role이 올바르지 않습니다."
        )
    if target.id == project.owner_user_id and role != "owner":
        raise ApiProblem(
            409,
            "project_owner_protected",
            "Project owner는 owner role로만 등록할 수 있습니다.",
        )
    existing = db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.user_id == target.id,
        )
    )
    if existing is not None:
        if existing.status == "active" and existing.role == role:
            return existing, target, False
        raise ApiProblem(
            409,
            "project_membership_exists",
            "이미 Project membership이 있습니다. 현재 상태를 조건부로 수정해 주세요.",
            details={"currentRole": existing.role, "currentStatus": existing.status},
        )
    membership = ProjectMembership(
        project_id=project.id,
        user_id=target.id,
        role=role,
        status="active",
        created_by_user_id=actor.id,
    )
    db.add(membership)
    db.flush()
    return membership, target, True


def require_nested_membership(
    db: Session, project_id: str, membership_id: str
) -> ProjectMembership:
    membership = db.get(ProjectMembership, membership_id)
    if membership is None or membership.project_id != project_id:
        raise ApiProblem(
            404,
            "project_membership_not_found",
            "Project membership을 찾을 수 없습니다.",
        )
    return membership


def _protect_owner_transition(
    db: Session,
    *,
    project: Project,
    membership: ProjectMembership,
    next_role: str,
    next_status: str,
) -> None:
    removes_owner = (
        membership.role == "owner"
        and membership.status == "active"
        and (next_role != "owner" or next_status != "active")
    )
    if not removes_owner:
        return
    db.execute(
        select(Project.id).where(Project.id == project.id).with_for_update()
    ).all()
    owner_count = db.scalar(
        select(func.count(ProjectMembership.id)).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.role == "owner",
            ProjectMembership.status == "active",
        )
    )
    if int(owner_count or 0) <= 1:
        raise ApiProblem(
            409,
            "last_project_owner_required",
            "Project에는 active owner가 최소 한 명 필요합니다.",
        )


def change_membership(
    db: Session,
    *,
    actor: User,
    project_id: str,
    membership_id: str,
    role: str | None,
    status: str | None,
    expected_role: str,
    expected_status: str,
) -> tuple[ProjectMembership, User, bool]:
    project = require_membership_manager(db, actor, project_id)
    membership = require_nested_membership(db, project.id, membership_id)
    target = db.get(User, membership.user_id)
    if target is None or target.organization_id != project.organization_id:
        raise ApiProblem(
            404,
            "project_membership_not_found",
            "Project membership을 찾을 수 없습니다.",
        )
    if membership.role != expected_role or membership.status != expected_status:
        raise _membership_conflict(membership)
    next_role = role or membership.role
    next_status = status or membership.status
    if next_role not in PROJECT_ROLES or next_status not in MEMBERSHIP_STATUSES:
        raise ApiProblem(
            422,
            "invalid_project_membership",
            "Project membership 값이 올바르지 않습니다.",
        )
    if next_status == "active" and target.status != "active":
        raise ApiProblem(
            409,
            "organization_user_inactive",
            "비활성 사용자의 Project membership은 활성화할 수 없습니다.",
        )
    changes_owner_membership = membership.user_id == project.owner_user_id and (
        next_role != membership.role or next_status != membership.status
    )
    if (
        changes_owner_membership
        and project.is_default
        and project.project_type == "personal"
    ):
        raise ApiProblem(
            409,
            "default_project_owner_protected",
            "Default 개인 Project의 owner는 변경하거나 회수할 수 없습니다.",
        )
    if changes_owner_membership:
        raise ApiProblem(
            409,
            "project_owner_protected",
            "Project 소유권을 이전하기 전에는 owner를 변경하거나 회수할 수 없습니다.",
        )
    _protect_owner_transition(
        db,
        project=project,
        membership=membership,
        next_role=next_role,
        next_status=next_status,
    )
    if next_role == membership.role and next_status == membership.status:
        return membership, target, False
    result = db.execute(
        update(ProjectMembership)
        .where(
            ProjectMembership.id == membership.id,
            ProjectMembership.project_id == project.id,
            ProjectMembership.role == expected_role,
            ProjectMembership.status == expected_status,
        )
        .values(role=next_role, status=next_status, updated_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        db.expire(membership)
        db.refresh(membership)
        raise _membership_conflict(membership)
    db.expire(membership)
    db.refresh(membership)
    return membership, target, True


def revoke_membership(
    db: Session,
    *,
    actor: User,
    project_id: str,
    membership_id: str,
    expected_role: str,
    expected_status: str,
) -> tuple[ProjectMembership, User, bool]:
    return change_membership(
        db,
        actor=actor,
        project_id=project_id,
        membership_id=membership_id,
        role=None,
        status="revoked",
        expected_role=expected_role,
        expected_status=expected_status,
    )


def _membership_conflict(membership: ProjectMembership) -> ApiProblem:
    return ApiProblem(
        409,
        "project_membership_conflict",
        "Project membership이 다른 작업에서 변경되었습니다.",
        details={"currentRole": membership.role, "currentStatus": membership.status},
    )


def membership_payload(
    membership: ProjectMembership, target: User, project: Project | None = None
) -> dict[str, object]:
    return {
        "id": membership.id,
        "projectId": membership.project_id,
        "userId": target.id,
        "loginId": target.login_id,
        "displayName": target.display_name or target.login_id,
        "accountStatus": target.status,
        "role": membership.role,
        "status": membership.status,
        "isProjectOwner": bool(project and project.owner_user_id == target.id),
        "createdByUserId": membership.created_by_user_id,
        "createdAt": membership.created_at,
        "updatedAt": membership.updated_at,
    }
