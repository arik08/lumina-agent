from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..authorization import require_project
from ..memories.policy import normalize_fact, validate_memory_text
from ..models import (
    Project,
    ProjectLearningProposal,
    ProjectMembership,
    ProjectMemory,
    Run,
    User,
    new_uuid,
    utc_now,
)
from ..projects.service import concept_digest
from .schemas import ProjectLearningEvidence


EMPTY_HASH = hashlib.sha256(b"").hexdigest()
_PROJECT_SENSITIVE = re.compile(
    r"(?i)(?:[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|"
    r"\b01[016789][ -]?\d{3,4}[ -]?\d{4}\b|"
    r"개인\s*계정|personal\s+account|이번만\s*승인|일회성\s*승인|"
    r"임시\s*승인|temporary\s+approval|우회(?:책|방법)?|bypass)"
)
_TERM = re.compile(r"[A-Za-z0-9_]{2,}|[가-힣]{2,}")


def _validate_project_text(*values: str) -> None:
    validate_memory_text(*values)
    if any(_PROJECT_SENSITIVE.search(value) for value in values):
        raise ApiProblem(
            422,
            "sensitive_project_learning_forbidden",
            "개인정보, 개인 계정, 일회성 승인 또는 임시 우회책은 Project 학습에 저장할 수 없습니다.",
        )


def _memory_hash(category: str, normalized_fact: str, display_text: str) -> str:
    canonical = json.dumps(
        {
            "category": category,
            "normalized_fact": normalized_fact,
            "display_text": display_text,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _active_memory(
    db: Session, project_id: str, memory_key: str
) -> ProjectMemory | None:
    return db.scalar(
        select(ProjectMemory).where(
            ProjectMemory.project_id == project_id,
            ProjectMemory.memory_key == memory_key,
            ProjectMemory.status == "active",
        )
    )


def _require_reviewer(db: Session, user: User, project_id: str) -> Project:
    project = require_project(db, user, project_id, write=True)
    if user.role == "admin" or project.owner_user_id == user.id:
        return project
    membership = db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user.id,
            ProjectMembership.status == "active",
            ProjectMembership.role.in_(("owner", "admin")),
        )
    )
    if membership is None:
        raise ApiProblem(
            403,
            "project_review_required",
            "Project owner 또는 admin만 메모리 반영 제안을 검토할 수 있습니다.",
        )
    return project


def _validate_sources(
    db: Session, project_id: str, source_run_ids: Sequence[str]
) -> list[str]:
    result: list[str] = []
    for run_id in dict.fromkeys(source_run_ids):
        run = db.get(Run, run_id)
        if run is None or run.project_id != project_id or run.status != "completed":
            raise ApiProblem(
                404,
                "project_learning_source_not_found",
                "완료된 Project Run만 메모리 반영 제안의 출처로 사용할 수 있습니다.",
            )
        result.append(run.id)
    return result


def _canonical_patch(
    target_type: str,
    target: ProjectMemory | None,
    patch: dict[str, object],
) -> dict[str, Any]:
    if target_type == "project_concept":
        if set(patch) != {"concept"} or not isinstance(patch.get("concept"), str):
            raise ApiProblem(
                422,
                "invalid_project_learning_patch",
                "Project concept 제안에는 concept 문자열만 포함할 수 있습니다.",
            )
        concept = str(patch["concept"])
        if len(concept) > 20_000:
            raise ApiProblem(
                422, "invalid_project_learning_patch", "Project concept가 너무 깁니다."
            )
        _validate_project_text(concept)
        return {"concept": concept}

    if patch == {"delete": True}:
        if target is None:
            raise ApiProblem(
                422,
                "invalid_project_learning_patch",
                "존재하는 Project Memory만 삭제할 수 있습니다.",
            )
        return {"delete": True}
    allowed = {"category", "fact", "displayText"}
    if not patch or not set(patch) <= allowed:
        raise ApiProblem(
            422,
            "invalid_project_learning_patch",
            "Project Memory 제안 필드가 올바르지 않습니다.",
        )
    current = (
        {
            "category": target.category,
            "fact": target.normalized_fact,
            "displayText": target.display_text,
        }
        if target is not None
        else {}
    )
    merged = {**current, **patch}
    if set(merged) != allowed or not all(
        isinstance(merged[key], str) for key in allowed
    ):
        raise ApiProblem(
            422,
            "invalid_project_learning_patch",
            "새 Project Memory에는 category, fact와 displayText가 모두 필요합니다.",
        )
    category = str(merged["category"]).strip()
    fact = str(merged["fact"]).strip()
    display_text = str(merged["displayText"]).strip()
    if not (
        0 < len(category) <= 80
        and 0 < len(fact) <= 1000
        and 0 < len(display_text) <= 4000
    ):
        raise ApiProblem(
            422,
            "invalid_project_learning_patch",
            "Project Memory 내용 길이가 올바르지 않습니다.",
        )
    _validate_project_text(category, fact, display_text)
    return {
        "category": category,
        "fact": fact,
        "displayText": display_text,
    }


def create_proposal(
    db: Session,
    *,
    user: User,
    project_id: str,
    source_run_ids: list[str],
    target_type: str,
    target_id: str | None,
    base_revision: int,
    base_hash: str,
    proposed_patch: dict[str, object],
    rationale: str,
    evidence_refs: Sequence[ProjectLearningEvidence],
) -> ProjectLearningProposal:
    project = require_project(db, user, project_id, write=True)
    sources = _validate_sources(db, project_id, source_run_ids)
    target: ProjectMemory | None = None
    if target_type == "project_memory":
        if target_id is not None:
            target = _active_memory(db, project_id, target_id)
            if target is None:
                raise ApiProblem(
                    404,
                    "project_memory_not_found",
                    "Project Memory를 찾을 수 없습니다.",
                )
            if target.revision != base_revision or target.content_hash != base_hash:
                raise ApiProblem(
                    409,
                    "project_learning_base_conflict",
                    "Project Memory가 이미 변경되었습니다.",
                )
        elif base_revision != 0 or base_hash != EMPTY_HASH:
            raise ApiProblem(
                409,
                "project_learning_base_conflict",
                "새 Project Memory의 base가 올바르지 않습니다.",
            )
    elif target_type == "project_concept":
        if (
            target_id is not None
            or project.concept_revision != base_revision
            or project.concept_hash != base_hash
        ):
            raise ApiProblem(
                409,
                "project_learning_base_conflict",
                "Project concept가 이미 변경되었습니다.",
            )
    else:
        raise ApiProblem(
            422,
            "invalid_project_learning_target",
            "지원하지 않는 Project 학습 대상입니다.",
        )
    canonical_patch = _canonical_patch(target_type, target, proposed_patch)
    if (
        len(json.dumps(canonical_patch, ensure_ascii=False, separators=(",", ":")))
        > 50_000
    ):
        raise ApiProblem(
            422,
            "invalid_project_learning_patch",
            "Project 메모리 반영 제안이 허용 크기를 초과했습니다.",
        )
    evidence = [item.model_dump(mode="json", by_alias=False) for item in evidence_refs]
    _validate_project_text(
        rationale,
        *(str(item.get("note", "")) for item in evidence),
    )
    proposal = ProjectLearningProposal(
        organization_id=project.organization_id,
        project_id=project.id,
        source_run_ids_json=sources,
        target_type=target_type,
        target_id=target_id,
        base_revision=base_revision,
        base_hash=base_hash,
        proposed_patch_json=canonical_patch,
        rationale=rationale,
        evidence_refs_json=evidence,
        expected_scope="project",
        status="proposed",
        proposed_by_user_id=user.id,
    )
    db.add(proposal)
    db.flush()
    return proposal


def list_project_memories(
    db: Session, *, user: User, project_id: str, include_history: bool = False
) -> list[ProjectMemory]:
    require_project(db, user, project_id)
    statement = select(ProjectMemory).where(ProjectMemory.project_id == project_id)
    if not include_history:
        statement = statement.where(ProjectMemory.status == "active")
    return list(
        db.scalars(
            statement.order_by(
                ProjectMemory.memory_key,
                ProjectMemory.revision.desc(),
                ProjectMemory.id,
            )
        )
    )


def get_project_memory_history(
    db: Session, *, user: User, project_id: str, memory_key: str
) -> list[ProjectMemory]:
    require_project(db, user, project_id)
    rows = list(
        db.scalars(
            select(ProjectMemory)
            .where(
                ProjectMemory.project_id == project_id,
                ProjectMemory.memory_key == memory_key,
            )
            .order_by(ProjectMemory.revision.desc())
        )
    )
    if not rows:
        raise ApiProblem(
            404, "project_memory_not_found", "Project Memory를 찾을 수 없습니다."
        )
    return rows


def list_proposals(
    db: Session, *, user: User, project_id: str, status: str | None = None
) -> list[ProjectLearningProposal]:
    require_project(db, user, project_id)
    statement = select(ProjectLearningProposal).where(
        ProjectLearningProposal.project_id == project_id
    )
    if status is not None:
        statement = statement.where(ProjectLearningProposal.status == status)
    return list(
        db.scalars(
            statement.order_by(
                ProjectLearningProposal.created_at.desc(),
                ProjectLearningProposal.id,
            )
        )
    )


def require_proposal(
    db: Session,
    *,
    user: User,
    project_id: str,
    proposal_id: str,
    review: bool = False,
    for_update: bool = False,
) -> ProjectLearningProposal:
    if review:
        _require_reviewer(db, user, project_id)
    else:
        require_project(db, user, project_id)
    statement = select(ProjectLearningProposal).where(
        ProjectLearningProposal.id == proposal_id,
        ProjectLearningProposal.project_id == project_id,
    )
    if for_update:
        statement = statement.with_for_update()
    proposal = db.scalar(statement)
    if proposal is None:
        raise ApiProblem(
            404, "project_learning_proposal_not_found", "메모리 반영 제안을 찾을 수 없습니다."
        )
    return proposal


def _base_matches(
    db: Session, project: Project, proposal: ProjectLearningProposal
) -> bool:
    if proposal.target_type == "project_concept":
        return (
            project.concept_revision == proposal.base_revision
            and project.concept_hash == proposal.base_hash
        )
    if proposal.target_id is None:
        return proposal.base_revision == 0 and proposal.base_hash == EMPTY_HASH
    target = _active_memory(db, project.id, proposal.target_id)
    return (
        target is not None
        and target.revision == proposal.base_revision
        and target.content_hash == proposal.base_hash
    )


def _mark_stale(proposal: ProjectLearningProposal, reviewer: User) -> None:
    proposal.status = "stale"
    proposal.reviewed_by_user_id = reviewer.id
    proposal.reviewed_at = utc_now()
    proposal.updated_at = proposal.reviewed_at


def approve_proposal(
    db: Session, *, user: User, project_id: str, proposal_id: str, note: str
) -> ProjectLearningProposal:
    project = _require_reviewer(db, user, project_id)
    proposal = require_proposal(
        db,
        user=user,
        project_id=project_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.status != "proposed":
        raise ApiProblem(
            409, "project_learning_invalid_state", "제안 상태에서만 승인할 수 있습니다."
        )
    _validate_project_text(note)
    if not _base_matches(db, project, proposal):
        _mark_stale(proposal, user)
        db.flush()
        return proposal
    now = utc_now()
    proposal.status = "approved"
    proposal.review_note = note or None
    proposal.reviewed_by_user_id = user.id
    proposal.reviewed_at = now
    proposal.approved_at = now
    proposal.updated_at = now
    db.flush()
    return proposal


def reject_proposal(
    db: Session, *, user: User, project_id: str, proposal_id: str, note: str
) -> ProjectLearningProposal:
    _require_reviewer(db, user, project_id)
    proposal = require_proposal(
        db,
        user=user,
        project_id=project_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.status not in {"proposed", "approved"}:
        raise ApiProblem(
            409, "project_learning_invalid_state", "이 제안은 거절할 수 없습니다."
        )
    _validate_project_text(note)
    now = utc_now()
    proposal.status = "rejected"
    proposal.review_note = note or None
    proposal.reviewed_by_user_id = user.id
    proposal.reviewed_at = now
    proposal.rejected_at = now
    proposal.updated_at = now
    db.flush()
    return proposal


def apply_proposal(
    db: Session, *, user: User, project_id: str, proposal_id: str
) -> tuple[ProjectLearningProposal, ProjectMemory | None]:
    project = _require_reviewer(db, user, project_id)
    proposal = require_proposal(
        db,
        user=user,
        project_id=project_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.status != "approved":
        raise ApiProblem(
            409, "project_learning_invalid_state", "승인된 제안만 적용할 수 있습니다."
        )
    if not _base_matches(db, project, proposal):
        _mark_stale(proposal, user)
        db.flush()
        return proposal, None
    applied_memory: ProjectMemory | None = None
    if proposal.target_type == "project_concept":
        previous = {
            "concept": project.concept,
            "revision": project.concept_revision,
            "hash": project.concept_hash,
        }
        concept = str(proposal.proposed_patch_json["concept"])
        next_revision = project.concept_revision + 1
        next_hash = concept_digest(concept)
        result = db.execute(
            update(Project)
            .where(
                Project.id == project.id,
                Project.concept_revision == proposal.base_revision,
                Project.concept_hash == proposal.base_hash,
            )
            .values(
                concept=concept,
                concept_revision=next_revision,
                concept_hash=next_hash,
                updated_at=utc_now(),
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", 0) != 1:
            _mark_stale(proposal, user)
            db.flush()
            return proposal, None
        db.expire(project)
        db.refresh(project)
        proposal.applied_snapshot_json = {
            "targetType": "project_concept",
            "previous": previous,
            "applied": {
                "concept": concept,
                "revision": project.concept_revision,
                "hash": project.concept_hash,
            },
        }
    else:
        previous_memory = (
            _active_memory(db, project.id, proposal.target_id)
            if proposal.target_id
            else None
        )
        patch = _canonical_patch(
            "project_memory", previous_memory, proposal.proposed_patch_json
        )
        deleting = patch == {"delete": True}
        if deleting and previous_memory is None:
            raise ApiProblem(
                409,
                "project_learning_base_conflict",
                "삭제할 Project Memory가 없습니다.",
            )
        if previous_memory is not None:
            result = db.execute(
                update(ProjectMemory)
                .where(
                    ProjectMemory.id == previous_memory.id,
                    ProjectMemory.status == "active",
                    ProjectMemory.revision == proposal.base_revision,
                    ProjectMemory.content_hash == proposal.base_hash,
                )
                .values(status="superseded")
                .execution_options(synchronize_session=False)
            )
            if getattr(result, "rowcount", 0) != 1:
                _mark_stale(proposal, user)
                db.flush()
                return proposal, None
            db.flush()
            memory_key = previous_memory.memory_key
            revision = previous_memory.revision + 1
        else:
            memory_key = new_uuid()
            revision = 1
        category = (
            previous_memory.category
            if deleting and previous_memory
            else str(patch["category"])
        )
        normalized = (
            previous_memory.normalized_fact
            if deleting and previous_memory
            else normalize_fact(str(patch["fact"]))
        )
        display_text = (
            previous_memory.display_text
            if deleting and previous_memory
            else str(patch["displayText"])
        )
        applied_memory = ProjectMemory(
            organization_id=project.organization_id,
            project_id=project.id,
            memory_key=memory_key,
            revision=revision,
            category=category,
            normalized_fact=normalized,
            display_text=display_text,
            content_hash=_memory_hash(category, normalized, display_text),
            status="deleted" if deleting else "active",
            parent_revision_id=previous_memory.id if previous_memory else None,
            source_proposal_id=proposal.id,
            source_run_ids_json=proposal.source_run_ids_json,
            created_by_user_id=user.id,
        )
        db.add(applied_memory)
        db.flush()
        proposal.target_id = memory_key
        proposal.applied_snapshot_json = {
            "targetType": "project_memory",
            "memoryKey": memory_key,
            "previousRevisionId": previous_memory.id if previous_memory else None,
            "appliedRevisionId": applied_memory.id,
            "appliedRevision": applied_memory.revision,
            "appliedHash": applied_memory.content_hash,
            "deleted": deleting,
        }
    proposal.status = "applied"
    proposal.applied_at = utc_now()
    proposal.updated_at = proposal.applied_at
    db.flush()
    return proposal, applied_memory


def rollback_proposal(
    db: Session, *, user: User, project_id: str, proposal_id: str
) -> tuple[ProjectLearningProposal, ProjectMemory | None]:
    project = _require_reviewer(db, user, project_id)
    proposal = require_proposal(
        db,
        user=user,
        project_id=project_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.status != "applied":
        raise ApiProblem(
            409, "project_learning_invalid_state", "적용된 제안만 되돌릴 수 있습니다."
        )
    snapshot = proposal.applied_snapshot_json
    rollback_memory: ProjectMemory | None = None
    if proposal.target_type == "project_concept":
        applied = snapshot.get("applied", {})
        previous = snapshot.get("previous", {})
        if (
            not isinstance(applied, dict)
            or not isinstance(previous, dict)
            or project.concept_revision != applied.get("revision")
            or project.concept_hash != applied.get("hash")
        ):
            _mark_stale(proposal, user)
            db.flush()
            return proposal, None
        concept = str(previous.get("concept", ""))
        next_revision = project.concept_revision + 1
        next_hash = concept_digest(concept)
        result = db.execute(
            update(Project)
            .where(
                Project.id == project.id,
                Project.concept_revision == applied.get("revision"),
                Project.concept_hash == applied.get("hash"),
            )
            .values(
                concept=concept,
                concept_revision=next_revision,
                concept_hash=next_hash,
                updated_at=utc_now(),
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", 0) != 1:
            _mark_stale(proposal, user)
            db.flush()
            return proposal, None
        db.expire(project)
        db.refresh(project)
        proposal.applied_snapshot_json = {
            **snapshot,
            "rollback": {
                "concept": concept,
                "revision": project.concept_revision,
                "hash": project.concept_hash,
            },
        }
    else:
        memory_key = str(snapshot.get("memoryKey", ""))
        current = _active_memory(db, project.id, memory_key)
        applied_id = snapshot.get("appliedRevisionId")
        applied_revision = (
            db.get(ProjectMemory, applied_id) if isinstance(applied_id, str) else None
        )
        deleted_application = snapshot.get("deleted") is True
        valid_applied_state = (
            applied_revision is not None
            and applied_revision.project_id == project.id
            and (
                (
                    deleted_application
                    and current is None
                    and applied_revision.status == "deleted"
                )
                or (
                    not deleted_application
                    and current is not None
                    and current.id == applied_revision.id
                )
            )
        )
        if not valid_applied_state:
            _mark_stale(proposal, user)
            db.flush()
            return proposal, None
        assert applied_revision is not None
        expected_status = "deleted" if deleted_application else "active"
        result = db.execute(
            update(ProjectMemory)
            .where(
                ProjectMemory.id == applied_revision.id,
                ProjectMemory.status == expected_status,
            )
            .values(status="rolled_back")
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", 0) != 1:
            _mark_stale(proposal, user)
            db.flush()
            return proposal, None
        db.flush()
        previous_id = snapshot.get("previousRevisionId")
        previous = (
            db.get(ProjectMemory, previous_id) if isinstance(previous_id, str) else None
        )
        if previous is not None and previous.project_id == project.id:
            rollback_memory = ProjectMemory(
                organization_id=project.organization_id,
                project_id=project.id,
                memory_key=memory_key,
                revision=applied_revision.revision + 1,
                category=previous.category,
                normalized_fact=previous.normalized_fact,
                display_text=previous.display_text,
                content_hash=previous.content_hash,
                status="active",
                parent_revision_id=applied_revision.id,
                source_proposal_id=proposal.id,
                source_run_ids_json=proposal.source_run_ids_json,
                created_by_user_id=user.id,
            )
            db.add(rollback_memory)
            db.flush()
        proposal.applied_snapshot_json = {
            **snapshot,
            "rollbackRevisionId": rollback_memory.id if rollback_memory else None,
        }
    proposal.status = "rolled_back"
    proposal.rolled_back_at = utc_now()
    proposal.updated_at = proposal.rolled_back_at
    db.flush()
    return proposal, rollback_memory


def select_relevant_project_memories(
    db: Session,
    *,
    project_id: str,
    query: str,
    limit: int = 6,
    character_budget: int = 6000,
) -> list[ProjectMemory]:
    memories = list(
        db.scalars(
            select(ProjectMemory).where(
                ProjectMemory.project_id == project_id,
                ProjectMemory.status == "active",
            )
        )
    )
    query_terms = _terms(query)
    ranked: list[tuple[int, int, str, ProjectMemory]] = []
    for memory in memories:
        overlap = len(
            query_terms
            & _terms(
                " ".join((memory.category, memory.normalized_fact, memory.display_text))
            )
        )
        always_relevant = memory.category == "project_rule"
        if not always_relevant and overlap == 0:
            continue
        ranked.append(
            (
                (1000 if always_relevant else 0) + overlap * 50,
                memory.revision,
                memory.id,
                memory,
            )
        )
    ranked.sort(key=lambda item: item[:3], reverse=True)
    selected: list[ProjectMemory] = []
    remaining = max(0, character_budget)
    for _score, _revision, _id, memory in ranked:
        length = len(memory.display_text) + len(memory.id) + len(memory.memory_key) + 64
        if length > remaining:
            continue
        selected.append(memory)
        remaining -= length
        if len(selected) >= max(0, limit):
            break
    return selected


def _terms(value: str) -> set[str]:
    terms: set[str] = set()
    for match in _TERM.findall(value.casefold()):
        terms.add(match)
        if any("가" <= character <= "힣" for character in match):
            terms.update(match[index : index + 2] for index in range(len(match) - 1))
    return terms


def memory_payload(memory: ProjectMemory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "projectId": memory.project_id,
        "memoryKey": memory.memory_key,
        "revision": memory.revision,
        "category": memory.category,
        "normalizedFact": memory.normalized_fact,
        "displayText": memory.display_text,
        "contentHash": memory.content_hash,
        "status": memory.status,
        "parentRevisionId": memory.parent_revision_id,
        "sourceProposalId": memory.source_proposal_id,
        "sourceRunIds": memory.source_run_ids_json,
        "createdByUserId": memory.created_by_user_id,
        "createdAt": memory.created_at,
    }


def proposal_payload(proposal: ProjectLearningProposal) -> dict[str, Any]:
    evidence_refs = []
    for item in proposal.evidence_refs_json:
        if not isinstance(item, dict):
            continue
        evidence_refs.append(
            {
                "kind": item.get("kind"),
                "referenceId": item.get("referenceId", item.get("reference_id")),
                "versionOrDigest": item.get(
                    "versionOrDigest", item.get("version_or_digest")
                ),
                "note": item.get("note", ""),
            }
        )
    return {
        "id": proposal.id,
        "projectId": proposal.project_id,
        "sourceRunIds": proposal.source_run_ids_json,
        "targetType": proposal.target_type,
        "targetId": proposal.target_id,
        "baseRevision": proposal.base_revision,
        "baseHash": proposal.base_hash,
        "proposedPatch": proposal.proposed_patch_json,
        "rationale": proposal.rationale,
        "reviewNote": proposal.review_note,
        "evidenceRefs": evidence_refs,
        "expectedScope": proposal.expected_scope,
        "status": proposal.status,
        "proposedByUserId": proposal.proposed_by_user_id,
        "reviewedByUserId": proposal.reviewed_by_user_id,
        "appliedSnapshot": proposal.applied_snapshot_json,
        "createdAt": proposal.created_at,
        "updatedAt": proposal.updated_at,
        "reviewedAt": proposal.reviewed_at,
        "approvedAt": proposal.approved_at,
        "rejectedAt": proposal.rejected_at,
        "appliedAt": proposal.applied_at,
        "rolledBackAt": proposal.rolled_back_at,
    }
