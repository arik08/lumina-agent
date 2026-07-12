from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...authorization import require_project
from ...db import get_db
from ...models import User
from ...projects.memberships import (
    add_membership,
    change_membership,
    list_memberships,
    membership_payload,
    revoke_membership,
)
from ...projects.schemas import (
    ProjectMembershipCreate,
    ProjectMembershipPatch,
    ProjectMembershipStatus,
    ProjectRole,
)
from ..dependencies import AuthContext, get_current_user, require_csrf


router = APIRouter(
    prefix="/projects/{project_id}/memberships", tags=["project-memberships"]
)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("")
def get_project_memberships(
    project_id: str,
    include_revoked: bool = Query(default=True, alias="includeRevoked"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    project = require_project(db, user, project_id)
    return [
        membership_payload(membership, target, project)
        for membership, target in list_memberships(
            db,
            user=user,
            project_id=project.id,
            include_revoked=include_revoked,
        )
    ]


@router.post("", status_code=201)
def post_project_membership(
    project_id: str,
    payload: ProjectMembershipCreate,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    membership, target, created = add_membership(
        db,
        actor=context.user,
        project_id=project_id,
        user_id=payload.user_id,
        login_id=payload.login_id,
        role=payload.role,
    )
    project = require_project(db, context.user, project_id)
    record_audit(
        db,
        action="project_membership_added"
        if created
        else "project_membership_confirmed",
        target_type="project_membership",
        target_id=membership.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "project_id": project.id,
            "target_user_id": target.id,
            "role": membership.role,
            "status": membership.status,
            "created": created,
        },
    )
    db.commit()
    if not created:
        response.status_code = 200
    return membership_payload(membership, target, project)


@router.patch("/{membership_id}")
def patch_project_membership(
    project_id: str,
    membership_id: str,
    payload: ProjectMembershipPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    membership, target, changed = change_membership(
        db,
        actor=context.user,
        project_id=project_id,
        membership_id=membership_id,
        role=payload.role,
        status=payload.status,
        expected_role=payload.expected_role,
        expected_status=payload.expected_status,
    )
    project = require_project(db, context.user, project_id)
    record_audit(
        db,
        action="project_membership_changed",
        target_type="project_membership",
        target_id=membership.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "project_id": project.id,
            "target_user_id": target.id,
            "previous_role": payload.expected_role,
            "previous_status": payload.expected_status,
            "role": membership.role,
            "status": membership.status,
            "changed": changed,
        },
    )
    db.commit()
    return membership_payload(membership, target, project)


@router.delete("/{membership_id}", status_code=204)
def delete_project_membership(
    project_id: str,
    membership_id: str,
    request: Request,
    expected_role: ProjectRole = Query(alias="expectedRole"),
    expected_status: ProjectMembershipStatus = Query(alias="expectedStatus"),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    membership, target, changed = revoke_membership(
        db,
        actor=context.user,
        project_id=project_id,
        membership_id=membership_id,
        expected_role=expected_role,
        expected_status=expected_status,
    )
    record_audit(
        db,
        action="project_membership_revoked",
        target_type="project_membership",
        target_id=membership.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "project_id": project_id,
            "target_user_id": target.id,
            "role": membership.role,
            "status": membership.status,
            "changed": changed,
        },
    )
    db.commit()
    return Response(status_code=204)
