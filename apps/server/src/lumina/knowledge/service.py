from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from sqlalchemy import case, exists, func, literal, or_, select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..config import Settings
from ..models import (
    KnowledgeEntity,
    KnowledgeEvidenceSegment,
    KnowledgeIngestionJob,
    KnowledgeRevision,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeSpace,
    KnowledgeStatement,
    KnowledgeStatementEvidence,
    ProviderModel,
    User,
    UserSetting,
    utc_now,
)
from ..providers.execution_defaults import initial_execution_selection
from .extractor import KNOWLEDGE_EXTRACTOR_VERSION
from .schemas import (
    EvidenceSegmentCreate,
    KnowledgeAutoCaptureUpdate,
    KnowledgeEntityCreate,
    KnowledgeReviewDecision,
    KnowledgeSourceCreate,
    KnowledgeSpaceCreate,
    KnowledgeSpaceUpdate,
    KnowledgeStatementCreate,
)


KNOWLEDGE_AUTO_CAPTURE_SETTING_KEY = "knowledge.auto_capture"


def knowledge_space_access_query(user: User, *, write: bool = False):
    query = select(KnowledgeSpace).where(
        KnowledgeSpace.organization_id == user.organization_id,
        KnowledgeSpace.archived_at.is_(None),
        KnowledgeSpace.status == "active",
    )
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


def list_knowledge_sources(
    db: Session, user: User, space_id: str
) -> list[
    tuple[KnowledgeSource, KnowledgeSourceRevision, list[KnowledgeEvidenceSegment]]
]:
    require_knowledge_space(db, user, space_id)
    sources = list(
        db.scalars(
            select(KnowledgeSource)
            .where(
                KnowledgeSource.space_id == space_id,
                KnowledgeSource.status == "active",
            )
            .order_by(KnowledgeSource.updated_at.desc(), KnowledgeSource.id)
        )
    )
    result: list[
        tuple[KnowledgeSource, KnowledgeSourceRevision, list[KnowledgeEvidenceSegment]]
    ] = []
    for source in sources:
        revision = db.scalar(
            select(KnowledgeSourceRevision)
            .where(KnowledgeSourceRevision.source_id == source.id)
            .order_by(KnowledgeSourceRevision.revision_number.desc())
            .limit(1)
        )
        if revision is None:
            continue
        evidence = list(
            db.scalars(
                select(KnowledgeEvidenceSegment)
                .where(KnowledgeEvidenceSegment.source_revision_id == revision.id)
                .order_by(KnowledgeEvidenceSegment.segment_ordinal)
            )
        )
        result.append((source, revision, evidence))
    return result


def list_knowledge_entities(
    db: Session, user: User, space_id: str
) -> list[KnowledgeEntity]:
    require_knowledge_space(db, user, space_id)
    return list(
        db.scalars(
            select(KnowledgeEntity)
            .where(
                KnowledgeEntity.space_id == space_id,
                KnowledgeEntity.status == "active",
            )
            .order_by(KnowledgeEntity.canonical_name, KnowledgeEntity.id)
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
    setting = db.scalar(
        select(UserSetting).where(
            UserSetting.user_id == user.id,
            UserSetting.key == KNOWLEDGE_AUTO_CAPTURE_SETTING_KEY,
        )
    )
    if setting is None:
        db.add(
            UserSetting(
                user_id=user.id,
                key=KNOWLEDGE_AUTO_CAPTURE_SETTING_KEY,
                value_json={"enabled": True, "spaceId": space.id, "mode": "research"},
            )
        )
    return space


def knowledge_auto_capture_payload(db: Session, user: User) -> dict[str, Any]:
    setting = db.scalar(
        select(UserSetting).where(
            UserSetting.user_id == user.id,
            UserSetting.key == KNOWLEDGE_AUTO_CAPTURE_SETTING_KEY,
        )
    )
    value = setting.value_json if setting is not None else None
    if isinstance(value, dict) and value.get("enabled") is False:
        return {"enabled": False, "spaceId": None, "mode": "research"}
    configured_space_id = value.get("spaceId") if isinstance(value, dict) else None
    space = None
    if isinstance(configured_space_id, str):
        space = db.scalar(
            knowledge_space_access_query(user, write=True).where(
                KnowledgeSpace.id == configured_space_id
            )
        )
    if space is None and setting is None:
        space = db.scalar(
            knowledge_space_access_query(user, write=True)
            .where(KnowledgeSpace.space_type == "personal")
            .order_by(KnowledgeSpace.created_at, KnowledgeSpace.id)
            .limit(1)
        )
    return {
        "enabled": space is not None,
        "spaceId": space.id if space is not None else None,
        "mode": "research",
    }


def update_knowledge_auto_capture(
    db: Session,
    user: User,
    payload: KnowledgeAutoCaptureUpdate,
) -> dict[str, Any]:
    space_id: str | None = None
    if payload.enabled:
        if payload.space_id is None:
            raise ApiProblem(
                422,
                "knowledge_auto_capture_space_required",
                "자동 축적을 켜려면 Knowledge Space를 선택해 주세요.",
            )
        space = require_knowledge_space(db, user, payload.space_id, write=True)
        space_id = space.id
    setting = db.scalar(
        select(UserSetting).where(
            UserSetting.user_id == user.id,
            UserSetting.key == KNOWLEDGE_AUTO_CAPTURE_SETTING_KEY,
        )
    )
    value = {"enabled": payload.enabled, "spaceId": space_id, "mode": "research"}
    if setting is None:
        setting = UserSetting(
            user_id=user.id,
            key=KNOWLEDGE_AUTO_CAPTURE_SETTING_KEY,
            value_json=value,
        )
        db.add(setting)
    else:
        setting.value_json = value
        setting.updated_at = utc_now()
    db.flush()
    return value


def update_knowledge_space(
    db: Session,
    user: User,
    space_id: str,
    payload: KnowledgeSpaceUpdate,
) -> KnowledgeSpace:
    space = require_knowledge_space(db, user, space_id, write=True)
    if space.settings_revision != payload.expected_revision:
        raise ApiProblem(
            409,
            "knowledge_space_revision_conflict",
            "지식 공간이 다른 곳에서 변경되었습니다. 최신 상태를 불러온 뒤 다시 시도해 주세요.",
            details={"currentRevision": space.settings_revision},
        )
    changed = False
    if payload.name is not None:
        space.name = payload.name.strip()
        changed = True
    if payload.description is not None:
        space.description = payload.description.strip()
        changed = True
    if payload.purpose is not None:
        space.purpose = payload.purpose.strip()
        changed = True
    if changed:
        space.settings_revision += 1
        space.updated_at = utc_now()
    db.flush()
    return space


def archive_knowledge_space(
    db: Session,
    user: User,
    space_id: str,
    *,
    expected_revision: int,
) -> KnowledgeSpace:
    space = require_knowledge_space(db, user, space_id, write=True)
    if space.settings_revision != expected_revision:
        raise ApiProblem(
            409,
            "knowledge_space_revision_conflict",
            "지식 공간이 다른 곳에서 변경되었습니다. 최신 상태를 불러온 뒤 다시 시도해 주세요.",
            details={"currentRevision": space.settings_revision},
        )
    space.status = "archived"
    space.archived_at = utc_now()
    space.settings_revision += 1
    space.updated_at = utc_now()
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


def create_knowledge_ingestion_job(
    db: Session,
    user: User,
    space_id: str,
    source_id: str,
    *,
    settings: Settings,
) -> tuple[KnowledgeIngestionJob, bool]:
    require_knowledge_space(db, user, space_id, write=True)
    source = db.get(KnowledgeSource, source_id)
    if source is None or source.space_id != space_id or source.status != "active":
        raise ApiProblem(
            404, "knowledge_source_not_found", "지식 원문을 찾을 수 없습니다."
        )
    revision = db.scalar(
        select(KnowledgeSourceRevision)
        .where(KnowledgeSourceRevision.source_id == source.id)
        .order_by(
            KnowledgeSourceRevision.revision_number.desc(),
            KnowledgeSourceRevision.id,
        )
        .limit(1)
    )
    if revision is None:
        raise ApiProblem(
            409,
            "knowledge_source_revision_missing",
            "지식 원문의 현재 revision을 찾을 수 없습니다.",
        )
    evidence_count = db.scalar(
        select(func.count(KnowledgeEvidenceSegment.id)).where(
            KnowledgeEvidenceSegment.source_revision_id == revision.id
        )
    )
    if not evidence_count:
        raise ApiProblem(
            422,
            "knowledge_evidence_required",
            "AI 추출에는 한 개 이상의 근거 구간이 필요합니다.",
        )
    execution = _resolve_knowledge_execution(db, user=user, settings=settings)
    existing = db.scalar(
        select(KnowledgeIngestionJob)
        .where(
            KnowledgeIngestionJob.source_revision_id == revision.id,
            KnowledgeIngestionJob.extractor_version == KNOWLEDGE_EXTRACTOR_VERSION,
            KnowledgeIngestionJob.provider_id == execution["provider_id"],
            KnowledgeIngestionJob.model_key == execution["model_key"],
            KnowledgeIngestionJob.status.in_(("queued", "running", "completed")),
        )
        .order_by(KnowledgeIngestionJob.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        return existing, False
    job = KnowledgeIngestionJob(
        space_id=space_id,
        source_id=source.id,
        source_revision_id=revision.id,
        requested_by_user_id=user.id,
        status="queued",
        provider_id=execution["provider_id"],
        model_key=execution["model_key"],
        runtime_model_id=execution["runtime_model_id"],
        extractor_version=KNOWLEDGE_EXTRACTOR_VERSION,
    )
    db.add(job)
    db.flush()
    return job, True


def _resolve_knowledge_execution(
    db: Session, *, user: User, settings: Settings
) -> dict[str, str]:
    setting = db.scalar(
        select(UserSetting).where(
            UserSetting.user_id == user.id,
            UserSetting.key == "execution.default",
        )
    )
    value = setting.value_json if setting is not None else None
    provider_id = (
        value.get("providerId", value.get("provider_id"))
        if isinstance(value, dict)
        else None
    )
    model_key = (
        value.get("modelKey", value.get("model_key"))
        if isinstance(value, dict)
        else None
    )
    if not isinstance(provider_id, str) or not isinstance(model_key, str):
        fallback, _source = initial_execution_selection(
            db,
            organization_id=user.organization_id,
            environment=settings.environment,
        )
        provider_id = str(fallback["providerId"])
        model_key = str(fallback["modelKey"])
    if provider_id == "mock":
        if settings.environment == "production":
            raise ApiProblem(
                409,
                "knowledge_provider_unavailable",
                "운영 환경에서는 Mock Provider로 지식을 추출할 수 없습니다.",
            )
        return {
            "provider_id": "mock",
            "model_key": "mock-agent",
            "runtime_model_id": "mock-agent",
        }
    model = db.scalar(
        select(ProviderModel).where(
            ProviderModel.provider_id == provider_id,
            ProviderModel.model_key == model_key,
            ProviderModel.enabled.is_(True),
        )
    )
    if model is None:
        fallback, _source = initial_execution_selection(
            db,
            organization_id=user.organization_id,
            environment=settings.environment,
        )
        fallback_provider_id = str(fallback["providerId"])
        fallback_model_key = str(fallback["modelKey"])
        if fallback_provider_id == "mock":
            if settings.environment == "production":
                raise ApiProblem(
                    409,
                    "knowledge_provider_unavailable",
                    "Knowledge 추출에 사용할 Provider 모델이 없습니다.",
                )
            return {
                "provider_id": "mock",
                "model_key": "mock-agent",
                "runtime_model_id": "mock-agent",
            }
        model = db.scalar(
            select(ProviderModel).where(
                ProviderModel.provider_id == fallback_provider_id,
                ProviderModel.model_key == fallback_model_key,
                ProviderModel.enabled.is_(True),
            )
        )
        if model is None:
            raise ApiProblem(
                409,
                "knowledge_provider_unavailable",
                "Knowledge 추출에 사용할 Provider 모델이 없습니다.",
            )
    if not bool(model.capabilities_json.get("structured_output")):
        raise ApiProblem(
            409,
            "knowledge_structured_output_required",
            "선택한 모델은 Knowledge 구조화 추출을 지원하지 않습니다.",
        )
    return {
        "provider_id": model.provider_id,
        "model_key": model.model_key,
        "runtime_model_id": model.runtime_model_id,
    }


def list_knowledge_ingestion_jobs(
    db: Session,
    user: User,
    space_id: str,
    *,
    source_id: str | None = None,
) -> list[KnowledgeIngestionJob]:
    require_knowledge_space(db, user, space_id)
    query = select(KnowledgeIngestionJob).where(
        KnowledgeIngestionJob.space_id == space_id
    )
    if source_id is not None:
        query = query.where(KnowledgeIngestionJob.source_id == source_id)
    return list(
        db.scalars(
            query.order_by(
                KnowledgeIngestionJob.created_at.desc(),
                KnowledgeIngestionJob.id,
            ).limit(200)
        )
    )


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
    current_statement = KnowledgeStatement.__table__.alias("current_statement")
    has_successor = exists(
        select(current_statement.c.id).where(
            current_statement.c.supersedes_statement_id == KnowledgeStatement.id
        )
    )
    return list(
        db.scalars(
            select(KnowledgeStatement)
            .where(
                KnowledgeStatement.space_id == space_id,
                ~has_successor,
            )
            .order_by(KnowledgeStatement.recorded_at.desc(), KnowledgeStatement.id)
        )
    )


def decide_knowledge_statement(
    db: Session,
    user: User,
    statement_id: str,
    payload: KnowledgeReviewDecision,
) -> KnowledgeStatement:
    statement = db.get(KnowledgeStatement, statement_id)
    if statement is None:
        raise ApiProblem(
            404, "knowledge_statement_not_found", "검토할 Statement를 찾을 수 없습니다."
        )
    require_knowledge_space(db, user, statement.space_id, write=True)
    if statement.status != "proposed":
        raise ApiProblem(
            409,
            "knowledge_statement_already_reviewed",
            "이미 검토가 끝난 Statement입니다.",
        )
    successor = db.scalar(
        select(KnowledgeStatement.id).where(
            KnowledgeStatement.supersedes_statement_id == statement.id
        )
    )
    if successor is not None:
        raise ApiProblem(
            409,
            "knowledge_statement_already_reviewed",
            "이미 검토가 끝난 Statement입니다.",
        )
    evidence_ids = list(
        db.scalars(
            select(KnowledgeStatementEvidence.evidence_segment_id).where(
                KnowledgeStatementEvidence.statement_id == statement.id
            )
        )
    )
    if payload.decision == "approved" and not evidence_ids:
        raise ApiProblem(
            422,
            "knowledge_evidence_required",
            "승인하려면 한 개 이상의 근거가 필요합니다.",
        )
    latest = db.scalar(
        select(KnowledgeRevision)
        .where(KnowledgeRevision.space_id == statement.space_id)
        .order_by(KnowledgeRevision.revision_number.desc())
        .limit(1)
    )
    revision_number = 1 if latest is None else latest.revision_number + 1
    digest = sha256(
        json.dumps(
            {
                "statementId": statement.id,
                "decision": payload.decision,
                "reason": payload.reason.strip(),
                "evidence": sorted(evidence_ids),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    revision = KnowledgeRevision(
        space_id=statement.space_id,
        revision_number=revision_number,
        parent_revision_id=latest.id if latest else None,
        status="approved",
        content_digest=digest,
        change_summary=payload.reason.strip()
        or ("Statement 승인" if payload.decision == "approved" else "Statement 거절"),
        created_by_user_id=user.id,
        approved_by_user_id=user.id,
        approved_at=utc_now(),
    )
    db.add(revision)
    db.flush()
    reviewed = KnowledgeStatement(
        space_id=statement.space_id,
        revision_id=revision.id,
        subject_entity_id=statement.subject_entity_id,
        predicate_key=statement.predicate_key,
        object_kind=statement.object_kind,
        object_entity_id=statement.object_entity_id,
        object_value_json=statement.object_value_json,
        status=payload.decision,
        rank="deprecated" if payload.decision == "rejected" else statement.rank,
        confidence=statement.confidence,
        valid_from=statement.valid_from,
        valid_to=statement.valid_to,
        created_by_type="user",
        created_by_user_id=user.id,
        supersedes_statement_id=statement.id,
    )
    db.add(reviewed)
    db.flush()
    db.add_all(
        KnowledgeStatementEvidence(
            statement_id=reviewed.id, evidence_segment_id=evidence_id
        )
        for evidence_id in evidence_ids
    )
    db.flush()
    return reviewed


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


def ingestion_job_payload(job: KnowledgeIngestionJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "spaceId": job.space_id,
        "sourceId": job.source_id,
        "sourceRevisionId": job.source_revision_id,
        "status": job.status,
        "providerId": job.provider_id,
        "modelKey": job.model_key,
        "extractorVersion": job.extractor_version,
        "inputSegmentCount": job.input_segment_count,
        "inputCharacterCount": job.input_character_count,
        "entityCount": job.entity_count,
        "statementCount": job.statement_count,
        "inputTokens": job.input_tokens,
        "outputTokens": job.output_tokens,
        "errorCode": job.error_code,
        "errorMessage": job.error_message,
        "queuedAt": job.queued_at,
        "startedAt": job.started_at,
        "finishedAt": job.finished_at,
        "createdAt": job.created_at,
        "updatedAt": job.updated_at,
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
