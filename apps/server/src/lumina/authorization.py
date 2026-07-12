from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .api.errors import ApiProblem
from .models import Conversation, Project, ProjectMembership, User


def project_access_query(user: User, *, write: bool = False):
    if user.role == "admin":
        return select(Project).where(Project.organization_id == user.organization_id)

    member_roles = (
        ("owner", "admin", "member")
        if write
        else (
            "owner",
            "admin",
            "member",
            "viewer",
        )
    )
    membership_project_ids = select(ProjectMembership.project_id).where(
        ProjectMembership.user_id == user.id,
        ProjectMembership.status == "active",
        ProjectMembership.role.in_(member_roles),
    )
    return select(Project).where(
        Project.organization_id == user.organization_id,
        or_(Project.owner_user_id == user.id, Project.id.in_(membership_project_ids)),
    )


def require_project(
    db: Session, user: User, project_id: str, *, write: bool = False
) -> Project:
    project = db.scalar(
        project_access_query(user, write=write).where(Project.id == project_id)
    )
    if project is None or project.archived_at is not None:
        raise ApiProblem(404, "not_found", "프로젝트를 찾을 수 없습니다.")
    return project


def conversation_access_query(user: User, *, write: bool = False):
    project_ids = project_access_query(user, write=write).with_only_columns(Project.id)
    query = select(Conversation).where(
        Conversation.deleted_at.is_(None),
        Conversation.project_id.in_(project_ids),
    )
    if user.role != "admin":
        query = query.where(
            or_(
                Conversation.owner_user_id == user.id,
                Conversation.project_id.in_(project_ids),
            )
        )
    return query


def require_conversation(
    db: Session, user: User, conversation_id: str, *, write: bool = False
) -> Conversation:
    conversation = db.scalar(
        conversation_access_query(user, write=write).where(
            Conversation.id == conversation_id
        )
    )
    if conversation is None:
        raise ApiProblem(404, "not_found", "대화를 찾을 수 없습니다.")
    return conversation


def require_admin(user: User) -> None:
    if user.role != "admin":
        raise ApiProblem(403, "admin_required", "관리자 권한이 필요합니다.")
