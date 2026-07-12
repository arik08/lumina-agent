from __future__ import annotations

import hashlib

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..authorization import project_access_query, require_project
from ..models import Conversation, Project, ProjectMembership, User, utc_now


def concept_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def list_projects(db: Session, user: User) -> list[Project]:
    query = project_access_query(user)
    if user.role == "admin":
        membership_project_ids = select(ProjectMembership.project_id).where(
            ProjectMembership.user_id == user.id,
            ProjectMembership.status == "active",
        )
        query = select(Project).where(
            Project.organization_id == user.organization_id,
            or_(
                Project.owner_user_id == user.id,
                Project.id.in_(membership_project_ids),
            ),
        )
    return list(
        db.scalars(
            query
            .where(Project.archived_at.is_(None))
            .order_by(Project.is_default.desc(), Project.updated_at.desc(), Project.id)
        )
    )


def create_project(
    db: Session, user: User, *, name: str, description: str = ""
) -> Project:
    project = Project(
        organization_id=user.organization_id,
        owner_user_id=user.id,
        name=name.strip(),
        description=description.strip() or None,
        project_type="personal",
        visibility="private",
        is_default=False,
        concept="",
        concept_revision=1,
        concept_hash=concept_digest(""),
    )
    db.add(project)
    db.flush()
    membership = ProjectMembership(
        project_id=project.id,
        user_id=user.id,
        role="owner",
        status="active",
        created_by_user_id=user.id,
    )
    db.add(membership)
    db.flush()
    return project


def update_project(
    db: Session,
    user: User,
    project_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    concept: str | None = None,
    archived: bool | None = None,
) -> Project:
    project = require_project(db, user, project_id, write=True)
    if name is not None:
        project.name = name.strip()
    if description is not None:
        project.description = description.strip() or None
    if concept is not None and concept != project.concept:
        project.concept = concept
        project.concept_revision += 1
        project.concept_hash = concept_digest(concept)
    if archived is not None:
        if project.is_default and archived:
            raise ApiProblem(
                409, "default_project_required", "기본 프로젝트는 보관할 수 없습니다."
            )
        project.archived_at = utc_now() if archived else None
    db.flush()
    return project


def archive_project(db: Session, user: User, project_id: str) -> None:
    project = require_project(db, user, project_id, write=True)
    if project.is_default:
        raise ApiProblem(
            409, "default_project_required", "기본 프로젝트는 삭제할 수 없습니다."
        )

    fallback = db.scalar(
        select(Project).where(
            Project.owner_user_id == user.id,
            Project.is_default.is_(True),
            Project.archived_at.is_(None),
        )
    )
    if fallback is None:
        raise ApiProblem(
            409, "default_project_missing", "기본 프로젝트를 찾을 수 없습니다."
        )

    conversations = db.scalars(
        select(Conversation).where(
            Conversation.project_id == project.id,
            Conversation.deleted_at.is_(None),
        )
    )
    for conversation in conversations:
        conversation.project_id = fallback.id
        conversation.revision += 1
    project.archived_at = utc_now()
    db.flush()
