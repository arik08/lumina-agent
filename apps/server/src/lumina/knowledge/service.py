from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..models import (
    KnowledgeEntity,
    KnowledgeEvidenceSegment,
    KnowledgeRevision,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeSpace,
    KnowledgeStatement,
    KnowledgeStatementEvidence,
    User,
    utc_now,
)
from .schemas import (
    EvidenceSegmentCreate,
    KnowledgeEntityCreate,
    KnowledgeSourceCreate,
    KnowledgeSpaceCreate,
    KnowledgeStatementCreate,
)


def knowledge_space_access_query(user: User, *, write: bool = False):
    query = select(KnowledgeSpace).where(
        KnowledgeSpace.organization_id == user.organization_id,
        KnowledgeSpace.archived_at.is_(None),
        KnowledgeSpace.status == "active",
    )
    if user.role == "admin":
        return query
    if write:
        return query.where(KnowledgeSpace.owner_user_id == user.id)
    return query.where(
        or_(
            KnowledgeSpace.owner_user_id == user.id,
            KnowledgeSpace.visibility == "organization",
        )
    )


def require_knowledge_space(
    db: Session, user: User, space_id: str, *, write: bool = False
) -> KnowledgeSpace:
    space = db.scalar(
        knowledge_space_access_query(user, write=write).where(
            KnowledgeSpace.id == space_id
        )
    )
    if space is None:
        raise ApiProblem(
            404, "knowledge_space_not_found", "지식 공간을 찾을 수 없습니다."
        )
    return space


def list_knowledge_spaces(db: Session, user: User) -> list[KnowledgeSpace]:
    return list(
        db.scalars(
            knowledge_space_access_query(user).order_by(
                KnowledgeSpace.updated_at.desc(), KnowledgeSpace.id
            )
        )
    )


def create_knowledge_space(
    db: Session, user: User, payload: KnowledgeSpaceCreate
) -> KnowledgeSpace:
    space = KnowledgeSpace(
        organization_id=user.organization_id,
        owner_user_id=user.id,
        space_type="personal",
        name=payload.name.strip(),
        description=payload.description.strip(),
        purpose=payload.purpose.strip(),
        visibility="private",
        status="active",
    )
    db.add(space)
    db.flush()
    return space


def create_knowledge_source(
    db: Session,
    user: User,
    space_id: str,
    payload: KnowledgeSourceCreate,
) -> tuple[
    KnowledgeSource, KnowledgeSourceRevision, list[KnowledgeEvidenceSegment], bool
]:
    require_knowledge_space(db, user, space_id, write=True)
    existing = db.execute(
        select(KnowledgeSource, KnowledgeSourceRevision)
        .join(
            KnowledgeSourceRevision,
            KnowledgeSourceRevision.source_id == KnowledgeSource.id,
        )
        .where(
            KnowledgeSource.space_id == space_id,
            KnowledgeSourceRevision.content_digest == payload.content_digest,
        )
        .order_by(KnowledgeSourceRevision.captured_at.desc())
    ).first()
    if existing is not None:
        source, revision = existing
        evidence = list(
            db.scalars(
                select(KnowledgeEvidenceSegment)
                .where(KnowledgeEvidenceSegment.source_revision_id == revision.id)
                .order_by(KnowledgeEvidenceSegment.segment_ordinal)
            )
        )
        return source, revision, evidence, False

    source = KnowledgeSource(
        space_id=space_id,
        owner_user_id=user.id,
        source_type=payload.source_type,
        title=payload.title.strip(),
        canonical_locator=payload.canonical_locator,
        status="active",
    )
    db.add(source)
    db.flush()
    revision = KnowledgeSourceRevision(
        source_id=source.id,
        revision_number=1,
        content_digest=payload.content_digest,
        media_type=payload.media_type,
        byte_size=payload.byte_size,
        storage_reference=payload.storage_reference,
        captured_text=payload.captured_text,
        parser_name=payload.parser_name,
        parser_version=payload.parser_version,
        parse_digest=payload.parse_digest,
        created_by_user_id=user.id,
    )
    db.add(revision)
    db.flush()
    evidence = _create_evidence_segments(db, revision.id, payload.evidence_segments)
    return source, revision, evidence, True


def _create_evidence_segments(
    db: Session,
    source_revision_id: str,
    segments: list[EvidenceSegmentCreate],
) -> list[KnowledgeEvidenceSegment]:
    created: list[KnowledgeEvidenceSegment] = []
    for ordinal, payload in enumerate(segments):
        text = payload.text.strip()
        segment = KnowledgeEvidenceSegment(
            source_revision_id=source_revision_id,
            segment_ordinal=ordinal,
            locator_json=payload.locator,
            text=text,
            text_digest=sha256(text.encode("utf-8")).hexdigest(),
            language=payload.language,
            token_count=payload.token_count,
        )
        db.add(segment)
        created.append(segment)
    db.flush()
    return created


def create_knowledge_entity(
    db: Session,
    user: User,
    space_id: str,
    payload: KnowledgeEntityCreate,
) -> tuple[KnowledgeEntity, bool]:
    require_knowledge_space(db, user, space_id, write=True)
    normalized_key = _normalize_entity_name(payload.canonical_name)
    entity_type = payload.entity_type.strip().casefold()
    existing = db.scalar(
        select(KnowledgeEntity).where(
            KnowledgeEntity.space_id == space_id,
            KnowledgeEntity.normalized_key == normalized_key,
            KnowledgeEntity.entity_type == entity_type,
            KnowledgeEntity.status == "active",
        )
    )
    if existing is not None:
        return existing, False
    entity = KnowledgeEntity(
        space_id=space_id,
        entity_type=entity_type,
        canonical_name=payload.canonical_name.strip(),
        normalized_key=normalized_key,
        description=payload.description.strip(),
        status="active",
    )
    db.add(entity)
    db.flush()
    return entity, True


def create_knowledge_statement(
    db: Session,
    user: User,
    space_id: str,
    payload: KnowledgeStatementCreate,
) -> KnowledgeStatement:
    require_knowledge_space(db, user, space_id, write=True)
    subject = _require_entity_in_space(db, payload.subject_entity_id, space_id)
    object_entity = None
    if payload.object_entity_id is not None:
        object_entity = _require_entity_in_space(db, payload.object_entity_id, space_id)
    evidence = _require_evidence_in_space(db, payload.evidence_segment_ids, space_id)

    latest = db.scalar(
        select(KnowledgeRevision)
        .where(KnowledgeRevision.space_id == space_id)
        .order_by(KnowledgeRevision.revision_number.desc())
        .limit(1)
    )
    revision_number = 1 if latest is None else latest.revision_number + 1
    digest_payload = {
        "subject": subject.id,
        "predicate": payload.predicate_key.strip(),
        "objectKind": payload.object_kind,
        "objectEntity": object_entity.id if object_entity else None,
        "objectValue": payload.object_value,
        "evidence": sorted(item.id for item in evidence),
        "status": payload.status,
        "rank": payload.rank,
        "validFrom": payload.valid_from,
        "validTo": payload.valid_to,
    }
    content_digest = sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    approved = payload.status == "approved"
    revision = KnowledgeRevision(
        space_id=space_id,
        revision_number=revision_number,
        parent_revision_id=latest.id if latest else None,
        status="approved" if approved else "review",
        content_digest=content_digest,
        change_summary=payload.change_summary.strip(),
        created_by_user_id=user.id,
        approved_by_user_id=user.id if approved else None,
        approved_at=utc_now() if approved else None,
    )
    db.add(revision)
    db.flush()
    statement = KnowledgeStatement(
        space_id=space_id,
        revision_id=revision.id,
        subject_entity_id=subject.id,
        predicate_key=payload.predicate_key.strip(),
        object_kind=payload.object_kind,
        object_entity_id=object_entity.id if object_entity else None,
        object_value_json=payload.object_value,
        status=payload.status,
        rank=payload.rank,
        confidence=payload.confidence,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        created_by_type="user",
        created_by_user_id=user.id,
    )
    db.add(statement)
    db.flush()
    db.add_all(
        KnowledgeStatementEvidence(
            statement_id=statement.id, evidence_segment_id=item.id
        )
        for item in evidence
    )
    db.flush()
    return statement


def list_knowledge_statements(
    db: Session, user: User, space_id: str
) -> list[KnowledgeStatement]:
    require_knowledge_space(db, user, space_id)
    return list(
        db.scalars(
            select(KnowledgeStatement)
            .where(KnowledgeStatement.space_id == space_id)
            .order_by(KnowledgeStatement.recorded_at.desc(), KnowledgeStatement.id)
        )
    )


def knowledge_neighborhood(
    db: Session,
    user: User,
    entity_id: str,
    *,
    max_depth: int,
    max_nodes: int,
    max_edges: int,
) -> dict[str, Any]:
    entity = db.get(KnowledgeEntity, entity_id)
    if entity is None:
        raise ApiProblem(
            404, "knowledge_entity_not_found", "Entity를 찾을 수 없습니다."
        )
    require_knowledge_space(db, user, entity.space_id)

    walk = select(literal(entity.id).label("entity_id"), literal(0).label("depth")).cte(
        "knowledge_walk", recursive=True
    )
    adjacent_id = case(
        (
            KnowledgeStatement.subject_entity_id == walk.c.entity_id,
            KnowledgeStatement.object_entity_id,
        ),
        else_=KnowledgeStatement.subject_entity_id,
    )
    step = select(
        adjacent_id.label("entity_id"), (walk.c.depth + 1).label("depth")
    ).where(
        KnowledgeStatement.space_id == entity.space_id,
        KnowledgeStatement.status == "approved",
        KnowledgeStatement.object_entity_id.is_not(None),
        walk.c.depth < max_depth,
        or_(
            KnowledgeStatement.subject_entity_id == walk.c.entity_id,
            KnowledgeStatement.object_entity_id == walk.c.entity_id,
        ),
    )
    walk = walk.union(step)
    depth_query = (
        select(walk.c.entity_id, func.min(walk.c.depth).label("depth"))
        .group_by(walk.c.entity_id)
        .order_by(func.min(walk.c.depth), walk.c.entity_id)
        .limit(max_nodes + 1)
    )
    depth_rows = list(db.execute(depth_query))
    nodes_truncated = len(depth_rows) > max_nodes
    depth_rows = depth_rows[:max_nodes]
    depth_by_id = {row.entity_id: row.depth for row in depth_rows}
    entity_ids = list(depth_by_id)
    entities = list(
        db.scalars(
            select(KnowledgeEntity)
            .where(KnowledgeEntity.id.in_(entity_ids))
            .order_by(KnowledgeEntity.id)
        )
    )
    edge_rows = list(
        db.scalars(
            select(KnowledgeStatement)
            .where(
                KnowledgeStatement.space_id == entity.space_id,
                KnowledgeStatement.status == "approved",
                KnowledgeStatement.subject_entity_id.in_(entity_ids),
                KnowledgeStatement.object_entity_id.in_(entity_ids),
            )
            .order_by(KnowledgeStatement.recorded_at, KnowledgeStatement.id)
            .limit(max_edges + 1)
        )
    )
    edges_truncated = len(edge_rows) > max_edges
    edge_rows = edge_rows[:max_edges]
    return {
        "rootEntityId": entity.id,
        "maxDepth": max_depth,
        "nodes": [
            entity_payload(item, depth=depth_by_id[item.id]) for item in entities
        ],
        "edges": [statement_payload(db, item) for item in edge_rows],
        "truncated": nodes_truncated or edges_truncated,
    }


def _require_entity_in_space(
    db: Session, entity_id: str, space_id: str
) -> KnowledgeEntity:
    entity = db.get(KnowledgeEntity, entity_id)
    if entity is None or entity.space_id != space_id or entity.status != "active":
        raise ApiProblem(
            404, "knowledge_entity_not_found", "Entity를 찾을 수 없습니다."
        )
    return entity


def _require_evidence_in_space(
    db: Session, evidence_ids: list[str], space_id: str
) -> list[KnowledgeEvidenceSegment]:
    unique_ids = list(dict.fromkeys(evidence_ids))
    if not unique_ids:
        return []
    evidence = list(
        db.scalars(
            select(KnowledgeEvidenceSegment)
            .join(
                KnowledgeSourceRevision,
                KnowledgeSourceRevision.id
                == KnowledgeEvidenceSegment.source_revision_id,
            )
            .join(
                KnowledgeSource,
                KnowledgeSource.id == KnowledgeSourceRevision.source_id,
            )
            .where(
                KnowledgeEvidenceSegment.id.in_(unique_ids),
                KnowledgeSource.space_id == space_id,
            )
        )
    )
    if len(evidence) != len(unique_ids):
        raise ApiProblem(
            404,
            "knowledge_evidence_not_found",
            "근거 자료를 찾을 수 없습니다.",
        )
    return evidence


def _normalize_entity_name(value: str) -> str:
    return " ".join(value.casefold().split())


def space_payload(space: KnowledgeSpace) -> dict[str, Any]:
    return {
        "id": space.id,
        "organizationId": space.organization_id,
        "ownerUserId": space.owner_user_id,
        "spaceType": space.space_type,
        "name": space.name,
        "description": space.description,
        "purpose": space.purpose,
        "visibility": space.visibility,
        "status": space.status,
        "settingsRevision": space.settings_revision,
        "createdAt": space.created_at,
        "updatedAt": space.updated_at,
    }


def source_payload(
    source: KnowledgeSource,
    revision: KnowledgeSourceRevision,
    evidence: list[KnowledgeEvidenceSegment],
) -> dict[str, Any]:
    return {
        "id": source.id,
        "spaceId": source.space_id,
        "sourceType": source.source_type,
        "title": source.title,
        "canonicalLocator": source.canonical_locator,
        "status": source.status,
        "revision": {
            "id": revision.id,
            "revisionNumber": revision.revision_number,
            "contentDigest": revision.content_digest,
            "mediaType": revision.media_type,
            "byteSize": revision.byte_size,
            "capturedAt": revision.captured_at,
        },
        "evidenceSegments": [evidence_payload(item) for item in evidence],
    }


def evidence_payload(evidence: KnowledgeEvidenceSegment) -> dict[str, Any]:
    return {
        "id": evidence.id,
        "sourceRevisionId": evidence.source_revision_id,
        "segmentOrdinal": evidence.segment_ordinal,
        "locator": evidence.locator_json,
        "text": evidence.text,
        "textDigest": evidence.text_digest,
        "language": evidence.language,
        "tokenCount": evidence.token_count,
    }


def entity_payload(
    entity: KnowledgeEntity, *, depth: int | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": entity.id,
        "spaceId": entity.space_id,
        "entityType": entity.entity_type,
        "canonicalName": entity.canonical_name,
        "description": entity.description,
        "status": entity.status,
        "createdAt": entity.created_at,
        "updatedAt": entity.updated_at,
    }
    if depth is not None:
        payload["depth"] = depth
    return payload


def statement_payload(db: Session, statement: KnowledgeStatement) -> dict[str, Any]:
    evidence_ids = list(
        db.scalars(
            select(KnowledgeStatementEvidence.evidence_segment_id)
            .where(KnowledgeStatementEvidence.statement_id == statement.id)
            .order_by(KnowledgeStatementEvidence.evidence_segment_id)
        )
    )
    revision = db.get(KnowledgeRevision, statement.revision_id)
    return {
        "id": statement.id,
        "spaceId": statement.space_id,
        "revisionId": statement.revision_id,
        "revisionNumber": revision.revision_number if revision else None,
        "subjectEntityId": statement.subject_entity_id,
        "predicateKey": statement.predicate_key,
        "objectKind": statement.object_kind,
        "objectEntityId": statement.object_entity_id,
        "objectValue": statement.object_value_json,
        "status": statement.status,
        "rank": statement.rank,
        "confidence": statement.confidence,
        "validFrom": statement.valid_from,
        "validTo": statement.valid_to,
        "evidenceSegmentIds": evidence_ids,
        "recordedAt": statement.recorded_at,
    }
