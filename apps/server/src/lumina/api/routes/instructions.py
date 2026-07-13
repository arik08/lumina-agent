from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...authorization import require_admin, require_project
from ...db import get_db
from ...instructions.schemas import (
    InstructionRevisionContentUpdate,
    InstructionRevisionLabelUpdate,
    InstructionUpdate,
    RuntimePromptUpdate,
)
from ...instructions.service import (
    InstructionSnapshot,
    RuntimePromptKey,
    instruction_payload,
    normalize_instruction_content,
    organization_instruction_snapshot,
    personal_instruction_snapshot,
    project_instruction_snapshot,
    runtime_prompt_documents,
    update_organization_instructions,
    update_personal_instructions,
    update_project_instructions,
    update_runtime_prompt,
)
from ...models import Organization, User
from ...projects.memberships import effective_project_role
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem


router = APIRouter(tags=["instructions"])


def _organization(db: Session, user: User) -> Organization:
    organization = db.get(Organization, user.organization_id)
    if organization is None:
        raise RuntimeError("Authenticated user's organization is unavailable")
    return organization


def _set_instruction_headers(response: Response, snapshot: InstructionSnapshot) -> None:
    response.headers["ETag"] = (
        f'"instructions:{snapshot.scope}:{snapshot.scope_id}:'
        f'r{snapshot.revision}:{snapshot.digest}"'
    )
    response.headers["Cache-Control"] = "no-store"


@router.get("/instructions/personal")
def get_personal_instructions(
    response: Response,
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    snapshot = personal_instruction_snapshot(user)
    _set_instruction_headers(response, snapshot)
    return instruction_payload(
        snapshot,
        editable=True,
        applies_to_shared_projects=False,
    )


@router.patch("/instructions/personal")
def patch_personal_instructions(
    payload: InstructionUpdate,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user, changed = update_personal_instructions(
        db,
        context.user,
        content=payload.content,
        expected_revision=payload.expected_revision,
        expected_digest=payload.expected_digest,
    )
    snapshot = personal_instruction_snapshot(user)
    record_audit(
        db,
        action="personal_instructions_changed"
        if changed
        else "personal_instructions_unchanged",
        target_type="user_instructions",
        target_id=user.id,
        result="success" if changed else "unchanged",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"revision": snapshot.revision, "digest": snapshot.digest},
    )
    db.commit()
    _set_instruction_headers(response, snapshot)
    return instruction_payload(
        snapshot,
        editable=True,
        applies_to_shared_projects=False,
    )


@router.get("/projects/{project_id}/instructions")
def get_project_instructions(
    project_id: str,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    project = require_project(db, user, project_id)
    role = effective_project_role(db, user=user, project=project)
    snapshot = project_instruction_snapshot(project)
    _set_instruction_headers(response, snapshot)
    return instruction_payload(
        snapshot,
        editable=role in {"owner", "admin", "member"},
        applies_to_shared_projects=True,
    )


@router.patch("/projects/{project_id}/instructions")
def patch_project_instructions(
    project_id: str,
    payload: InstructionUpdate,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    project = require_project(db, context.user, project_id, write=True)
    project, changed = update_project_instructions(
        db,
        project,
        content=payload.content,
        expected_revision=payload.expected_revision,
        expected_digest=payload.expected_digest,
    )
    snapshot = project_instruction_snapshot(project)
    record_audit(
        db,
        action="project_instructions_changed"
        if changed
        else "project_instructions_unchanged",
        target_type="project_instructions",
        target_id=project.id,
        result="success" if changed else "unchanged",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"revision": snapshot.revision, "digest": snapshot.digest},
    )
    db.commit()
    _set_instruction_headers(response, snapshot)
    return instruction_payload(
        snapshot,
        editable=True,
        applies_to_shared_projects=True,
    )


@router.get("/admin/organization/instructions")
def get_organization_instructions(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(user)
    organization = _organization(db, user)
    snapshot = organization_instruction_snapshot(organization)
    _set_instruction_headers(response, snapshot)
    payload = instruction_payload(
        snapshot,
        editable=True,
        applies_to_shared_projects=True,
    )
    payload["revisionLabels"] = organization.policy_revision_labels
    return payload


@router.patch("/admin/organization/instructions")
def patch_organization_instructions(
    payload: InstructionUpdate,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(context.user)
    organization, changed = update_organization_instructions(
        db,
        _organization(db, context.user),
        content=payload.content,
        expected_revision=payload.expected_revision,
        expected_digest=payload.expected_digest,
    )
    snapshot = organization_instruction_snapshot(organization)
    record_audit(
        db,
        action=(
            "organization_instructions_changed"
            if changed
            else "organization_instructions_unchanged"
        ),
        target_type="organization_instructions",
        target_id=organization.id,
        result="success" if changed else "unchanged",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"revision": snapshot.revision, "digest": snapshot.digest},
    )
    db.commit()
    _set_instruction_headers(response, snapshot)
    result = instruction_payload(
        snapshot,
        editable=True,
        applies_to_shared_projects=True,
    )
    result["revisionLabels"] = organization.policy_revision_labels
    return result


@router.get("/admin/runtime-prompts")
def get_runtime_prompts(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    require_admin(user)
    response.headers["Cache-Control"] = "no-store"
    return runtime_prompt_documents(db, _organization(db, user))


@router.patch("/admin/runtime-prompts/{prompt_key}")
def patch_runtime_prompt(
    prompt_key: RuntimePromptKey,
    payload: RuntimePromptUpdate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(context.user)
    document, changed = update_runtime_prompt(
        db,
        _organization(db, context.user),
        prompt_key=prompt_key,
        content=payload.content,
        expected_revision=payload.expected_revision,
        expected_digest=payload.expected_digest,
        updated_by_user_id=context.user.id,
    )
    record_audit(
        db,
        action="runtime_prompt_changed" if changed else "runtime_prompt_unchanged",
        target_type="runtime_prompt",
        target_id=f"{context.user.organization_id}:{prompt_key}",
        result="success" if changed else "unchanged",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={
            "prompt_key": prompt_key,
            "revision": document["revision"],
            "digest": document["digest"],
            "overridden": document["overridden"],
        },
    )
    db.commit()
    return document


@router.patch("/admin/organization/instructions/revisions/{revision}/label")
def patch_organization_instruction_revision_label(
    revision: int,
    payload: InstructionRevisionLabelUpdate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(context.user)
    organization = _organization(db, context.user)
    if revision < 1 or revision > organization.policy_revision:
        raise ApiProblem(404, "not_found", "지침 revision을 찾을 수 없습니다.")
    labels = dict(organization.policy_revision_labels or {})
    normalized = payload.label.strip()
    if normalized:
        labels[str(revision)] = normalized
    else:
        labels.pop(str(revision), None)
    organization.policy_revision_labels = labels
    record_audit(
        db,
        action="organization_instruction_revision_labeled",
        target_type="organization_instructions",
        target_id=organization.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"revision": revision, "label_set": bool(normalized)},
    )
    db.commit()
    return {"revision": revision, "label": normalized}


@router.get("/admin/organization/instructions/revisions/{revision}")
def get_organization_instruction_revision(
    revision: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(user)
    organization = _organization(db, user)
    if revision == organization.policy_revision:
        content = organization.policy_instructions
    else:
        content = (organization.policy_revision_contents or {}).get(str(revision))
    if content is None:
        raise ApiProblem(404, "not_found", "이 revision의 지침 본문은 기록되어 있지 않습니다.")
    return {
        "revision": revision,
        "label": (organization.policy_revision_labels or {}).get(str(revision), ""),
        "content": content,
    }


@router.patch("/admin/organization/instructions/revisions/{revision}")
def patch_organization_instruction_revision(
    revision: int,
    payload: InstructionRevisionContentUpdate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(context.user)
    organization = _organization(db, context.user)
    if revision < 1 or revision >= organization.policy_revision:
        raise ApiProblem(404, "not_found", "수정 가능한 과거 지침 revision을 찾을 수 없습니다.")
    contents = dict(organization.policy_revision_contents or {})
    if str(revision) not in contents:
        raise ApiProblem(404, "not_found", "이 revision의 지침 본문은 기록되어 있지 않습니다.")
    normalized = normalize_instruction_content(payload.content)
    contents[str(revision)] = normalized
    organization.policy_revision_contents = contents
    record_audit(
        db,
        action="organization_instruction_revision_content_changed",
        target_type="organization_instructions",
        target_id=organization.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"revision": revision},
    )
    db.commit()
    return {"revision": revision, "content": normalized}


__all__ = ["router"]
