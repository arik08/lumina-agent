from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...db import get_db
from ...models import Project, User
from ...projects.memberships import effective_project_role
from ...projects.service import (
    archive_project,
    create_project,
    list_projects,
    update_project,
)
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..schemas import ProjectCreate, ProjectPatch


router = APIRouter(prefix="/projects", tags=["projects"])


def _project_payload(project: Project, user: User, db: Session) -> dict[str, object]:
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "projectType": project.project_type,
        "role": effective_project_role(db, user=user, project=project),
        "isDefault": project.is_default,
        "concept": project.concept,
        "conceptRevision": project.concept_revision,
        "conceptHash": project.concept_hash,
        "createdAt": project.created_at,
        "updatedAt": project.updated_at,
    }


@router.get("")
def get_projects(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, object]]:
    return [_project_payload(project, user, db) for project in list_projects(db, user)]


@router.post("", status_code=201)
def post_project(
    payload: ProjectCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    project = create_project(
        db, context.user, name=payload.name, description=payload.description
    )
    record_audit(
        db,
        action="project_created",
        target_type="project",
        target_id=project.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return _project_payload(project, context.user, db)


@router.patch("/{project_id}")
def patch_project(
    project_id: str,
    payload: ProjectPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    project = update_project(
        db,
        context.user,
        project_id,
        name=payload.name,
        description=payload.description,
        concept=payload.concept,
        archived=payload.archived,
    )
    record_audit(
        db,
        action="project_settings_changed",
        target_type="project",
        target_id=project.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return _project_payload(project, context.user, db)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    archive_project(db, context.user, project_id)
    db.commit()
    return Response(status_code=204)
