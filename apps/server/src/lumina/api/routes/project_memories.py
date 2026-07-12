from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...db import get_db
from ...models import User
from ...project_memories.schemas import (
    ProjectLearningProposalCreate,
    ProjectLearningReview,
)
from ...project_memories.service import (
    apply_proposal,
    approve_proposal,
    create_proposal,
    get_project_memory_history,
    list_project_memories,
    list_proposals,
    memory_payload,
    proposal_payload,
    reject_proposal,
    require_proposal,
    rollback_proposal,
)
from ..dependencies import AuthContext, get_current_user, require_csrf


router = APIRouter(prefix="/projects/{project_id}", tags=["project-memory"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/memories")
def get_project_memories(
    project_id: str,
    include_history: bool = Query(default=False, alias="includeHistory"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        memory_payload(item)
        for item in list_project_memories(
            db, user=user, project_id=project_id, include_history=include_history
        )
    ]


@router.get("/memories/{memory_key}")
def get_project_memory(
    project_id: str,
    memory_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    revisions = get_project_memory_history(
        db, user=user, project_id=project_id, memory_key=memory_key
    )
    return {
        "memoryKey": memory_key,
        "current": next(
            (memory_payload(item) for item in revisions if item.status == "active"),
            None,
        ),
        "revisions": [memory_payload(item) for item in revisions],
    }


@router.get("/learning-proposals")
def get_learning_proposals(
    project_id: str,
    status: Literal[
        "proposed", "approved", "rejected", "stale", "applied", "rolled_back"
    ]
    | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        proposal_payload(item)
        for item in list_proposals(db, user=user, project_id=project_id, status=status)
    ]


@router.post("/learning-proposals", status_code=201)
def post_learning_proposal(
    project_id: str,
    payload: ProjectLearningProposalCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    proposal = create_proposal(
        db,
        user=context.user,
        project_id=project_id,
        source_run_ids=payload.source_run_ids,
        target_type=payload.target_type,
        target_id=payload.target_id,
        base_revision=payload.base_revision,
        base_hash=payload.base_hash,
        proposed_patch=payload.proposed_patch,
        rationale=payload.rationale,
        evidence_refs=payload.evidence_refs,
    )
    record_audit(
        db,
        action="project_learning_proposed",
        target_type="project_learning_proposal",
        target_id=proposal.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "project_id": project_id,
            "target_type": proposal.target_type,
            "source_run_count": len(proposal.source_run_ids_json),
        },
    )
    db.commit()
    return proposal_payload(proposal)


@router.get("/learning-proposals/{proposal_id}")
def get_learning_proposal(
    project_id: str,
    proposal_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return proposal_payload(
        require_proposal(db, user=user, project_id=project_id, proposal_id=proposal_id)
    )


def _audit_action(
    db: Session,
    *,
    request: Request,
    context: AuthContext,
    project_id: str,
    proposal_id: str,
    action: str,
    status: str,
) -> None:
    record_audit(
        db,
        action=action,
        target_type="project_learning_proposal",
        target_id=proposal_id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"project_id": project_id, "status": status},
    )


@router.post("/learning-proposals/{proposal_id}/approve")
def post_approve_learning_proposal(
    project_id: str,
    proposal_id: str,
    request: Request,
    payload: ProjectLearningReview | None = None,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    proposal = approve_proposal(
        db,
        user=context.user,
        project_id=project_id,
        proposal_id=proposal_id,
        note=payload.note if payload else "",
    )
    _audit_action(
        db,
        request=request,
        context=context,
        project_id=project_id,
        proposal_id=proposal.id,
        action=(
            "project_learning_approved"
            if proposal.status == "approved"
            else "project_learning_stale"
        ),
        status=proposal.status,
    )
    db.commit()
    return proposal_payload(proposal)


@router.post("/learning-proposals/{proposal_id}/reject")
def post_reject_learning_proposal(
    project_id: str,
    proposal_id: str,
    request: Request,
    payload: ProjectLearningReview | None = None,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    proposal = reject_proposal(
        db,
        user=context.user,
        project_id=project_id,
        proposal_id=proposal_id,
        note=payload.note if payload else "",
    )
    _audit_action(
        db,
        request=request,
        context=context,
        project_id=project_id,
        proposal_id=proposal.id,
        action="project_learning_rejected",
        status=proposal.status,
    )
    db.commit()
    return proposal_payload(proposal)


@router.post("/learning-proposals/{proposal_id}/apply")
def post_apply_learning_proposal(
    project_id: str,
    proposal_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    proposal, memory = apply_proposal(
        db, user=context.user, project_id=project_id, proposal_id=proposal_id
    )
    _audit_action(
        db,
        request=request,
        context=context,
        project_id=project_id,
        proposal_id=proposal.id,
        action=(
            "project_learning_applied"
            if proposal.status == "applied"
            else "project_learning_stale"
        ),
        status=proposal.status,
    )
    db.commit()
    return {
        "proposal": proposal_payload(proposal),
        "projectMemory": memory_payload(memory) if memory else None,
    }


@router.post("/learning-proposals/{proposal_id}/rollback")
def post_rollback_learning_proposal(
    project_id: str,
    proposal_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    proposal, memory = rollback_proposal(
        db, user=context.user, project_id=project_id, proposal_id=proposal_id
    )
    _audit_action(
        db,
        request=request,
        context=context,
        project_id=project_id,
        proposal_id=proposal.id,
        action=(
            "project_learning_rolled_back"
            if proposal.status == "rolled_back"
            else "project_learning_stale"
        ),
        status=proposal.status,
    )
    db.commit()
    return {
        "proposal": proposal_payload(proposal),
        "projectMemory": memory_payload(memory) if memory else None,
    }
