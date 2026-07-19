from __future__ import annotations

from collections.abc import Callable, Mapping
from hashlib import sha256
import logging
import re
from unicodedata import normalize

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..authorization import require_project
from ..messages.service import require_message
from ..models import (
    Conversation,
    KnowledgeDocument,
    KnowledgeDocumentTag,
    KnowledgeSpace,
    KnowledgeTag,
    KnowledgeTagAlias,
    Run,
    User,
)
from ..providers.types import ProviderAdapter
from .schemas import KnowledgeSpaceCreate, KnowledgeSpaceUpdate
from .tagger import (
    ExistingTagCandidate,
    MAX_DOCUMENT_TAGS,
    NewTagSuggestion,
    suggest_document_tags,
)


logger = logging.getLogger(__name__)
_GENERIC_TITLES = {"", "제목 없음", "새 작업", "새 채팅"}
_MARKDOWN_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_TAG_SPACE = re.compile(r"\s+")


def list_knowledge_spaces(db: Session, user: User) -> list[KnowledgeSpace]:
    return list(
        db.scalars(
            select(KnowledgeSpace)
            .where(
                KnowledgeSpace.owner_user_id == user.id,
                KnowledgeSpace.status == "active",
                KnowledgeSpace.archived_at.is_(None),
            )
            .order_by(KnowledgeSpace.created_at, KnowledgeSpace.id)
        )
    )


def create_knowledge_space(
    db: Session, user: User, payload: KnowledgeSpaceCreate
) -> KnowledgeSpace:
    space = KnowledgeSpace(
        owner_user_id=user.id,
        organization_id=user.organization_id,
        name=payload.name.strip(),
        description="",
        purpose=payload.purpose.strip(),
        visibility=payload.visibility,
        status="active",
        settings_revision=1,
    )
    db.add(space)
    db.flush()
    return space


def ensure_default_space(db: Session, user: User) -> KnowledgeSpace:
    existing = db.scalar(
        select(KnowledgeSpace)
        .where(
            KnowledgeSpace.owner_user_id == user.id,
            KnowledgeSpace.status == "active",
            KnowledgeSpace.archived_at.is_(None),
        )
        .order_by(KnowledgeSpace.created_at, KnowledgeSpace.id)
        .limit(1)
    )
    if existing is not None:
        return existing
    return create_knowledge_space(
        db,
        user,
        KnowledgeSpaceCreate(
            name="내 지식 그래프",
            purpose="AI 답변을 문서 단위로 저장하고 연결합니다.",
            visibility="private",
        ),
    )


def require_knowledge_space(
    db: Session, user: User, space_id: str, *, write: bool = False
) -> KnowledgeSpace:
    space = db.get(KnowledgeSpace, space_id)
    if (
        space is None
        or space.owner_user_id != user.id
        or space.status != "active"
        or space.archived_at is not None
    ):
        raise ApiProblem(404, "knowledge_space_not_found", "지식 공간을 찾을 수 없습니다.")
    return space


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
            "다른 변경이 먼저 저장되었습니다. 최신 설정을 다시 불러와 주세요.",
        )
    if payload.name is not None:
        space.name = payload.name.strip()
    if payload.purpose is not None:
        space.purpose = payload.purpose.strip()
    if payload.project_ids is not None:
        for project_id in payload.project_ids:
            require_project(db, user, project_id)
        space.project_ids_json = payload.project_ids
    space.settings_revision += 1
    db.flush()
    return space


def list_knowledge_documents(
    db: Session,
    user: User,
    *,
    space_id: str | None = None,
    project_id: str | None = None,
    query: str = "",
    limit: int = 200,
) -> list[KnowledgeDocument]:
    statement = select(KnowledgeDocument).where(
        KnowledgeDocument.owner_user_id == user.id,
        KnowledgeDocument.status == "active",
    )
    if space_id:
        require_knowledge_space(db, user, space_id)
        statement = statement.where(KnowledgeDocument.space_id == space_id)
    if project_id:
        statement = statement.where(KnowledgeDocument.project_id == project_id)
    normalized_query = " ".join(query.split()).strip()
    if normalized_query:
        statement = statement.where(
            or_(
                KnowledgeDocument.title.contains(normalized_query, autoescape=True),
                KnowledgeDocument.body.contains(normalized_query, autoescape=True),
            )
        )
    return list(
        db.scalars(
            statement.order_by(
                KnowledgeDocument.researched_at.desc(), KnowledgeDocument.id
            ).limit(limit)
        )
    )


def require_knowledge_document(
    db: Session, user: User, document_id: str
) -> KnowledgeDocument:
    document = db.get(KnowledgeDocument, document_id)
    if (
        document is None
        or document.owner_user_id != user.id
        or document.status != "active"
    ):
        raise ApiProblem(
            404, "knowledge_document_not_found", "지식 그래프 문서를 찾을 수 없습니다."
        )
    return document


async def save_message_as_knowledge_document(
    db: Session,
    user: User,
    message_id: str,
    *,
    provider_factory: Callable[[str], ProviderAdapter],
) -> tuple[KnowledgeDocument, bool]:
    existing = db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.source_message_id == message_id,
            KnowledgeDocument.owner_user_id == user.id,
        )
    )
    if existing is not None:
        return existing, False

    message = require_message(db, user, message_id, assistant_only=True)
    body = message.canonical_text.strip()
    if not body:
        raise ApiProblem(
            409,
            "knowledge_document_empty",
            "저장할 AI 답변 본문이 없습니다.",
        )
    conversation = db.get(Conversation, message.conversation_id)
    if conversation is None:
        raise ApiProblem(404, "conversation_not_found", "대화를 찾을 수 없습니다.")
    run = db.get(Run, message.run_id) if message.run_id else None
    space = ensure_default_space(db, user)
    title = _document_title(conversation.title, body)
    candidates = _tag_candidates(db, space.id)
    suggested_ids: tuple[str, ...] = ()
    new_tags: tuple[NewTagSuggestion, ...] = ()
    if run is not None:
        try:
            suggestion = await suggest_document_tags(
                provider=provider_factory(run.provider_id),
                model=run.runtime_model_id,
                title=title,
                body=body,
                candidates=candidates,
            )
            suggested_ids = suggestion.tag_ids
            new_tags = suggestion.new_tags
        except Exception:
            logger.warning(
                "Knowledge document tag generation failed; saving without generated tags",
                exc_info=True,
                extra={"message_id": message.id, "run_id": message.run_id},
            )

    document = KnowledgeDocument(
        space_id=space.id,
        project_id=conversation.project_id,
        owner_user_id=user.id,
        source_message_id=message.id,
        source_run_id=message.run_id,
        source_conversation_id=conversation.id,
        title=title,
        body=body,
        researched_at=(run.started_at if run and run.started_at else message.created_at),
        citations_json=_citation_snapshot(message.metadata_json),
        content_digest=sha256(body.encode("utf-8")).hexdigest(),
        status="active",
    )
    db.add(document)
    db.flush()
    tag_ids = _resolve_document_tags(
        db,
        space_id=space.id,
        suggested_ids=suggested_ids,
        new_tags=new_tags,
    )
    for tag_id in tag_ids[:MAX_DOCUMENT_TAGS]:
        db.add(KnowledgeDocumentTag(document_id=document.id, tag_id=tag_id))
    db.flush()
    return document, True


def document_payload(db: Session, document: KnowledgeDocument) -> dict[str, object]:
    tags = _document_tags(db, (document.id,)).get(document.id, [])
    return {
        "id": document.id,
        "spaceId": document.space_id,
        "projectId": document.project_id,
        "title": document.title,
        "body": document.body,
        "researchedAt": document.researched_at,
        "source": {
            "messageId": document.source_message_id,
            "runId": document.source_run_id,
            "conversationId": document.source_conversation_id,
        },
        "tags": tags,
        "citations": document.citations_json,
        "contentDigest": document.content_digest,
        "createdAt": document.created_at,
        "updatedAt": document.updated_at,
    }


def document_list_payload(
    db: Session, documents: list[KnowledgeDocument]
) -> list[dict[str, object]]:
    tags_by_document = _document_tags(db, tuple(item.id for item in documents))
    return [
        {
            "id": item.id,
            "spaceId": item.space_id,
            "projectId": item.project_id,
            "title": item.title,
            "researchedAt": item.researched_at,
            "tags": tags_by_document.get(item.id, []),
            "citationCount": len(item.citations_json),
            "bodyPreview": " ".join(item.body.split())[:240],
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
        }
        for item in documents
    ]


def knowledge_graph_payload(
    db: Session, user: User, *, space_id: str | None = None
) -> dict[str, object]:
    documents = list_knowledge_documents(
        db, user, space_id=space_id, limit=200
    )
    tags_by_document = _document_tags(db, tuple(item.id for item in documents))
    tag_ids_by_document = {
        document_id: {str(tag["id"]) for tag in tags}
        for document_id, tags in tags_by_document.items()
    }
    edges: list[dict[str, object]] = []
    for index, source in enumerate(documents):
        source_tags = tag_ids_by_document.get(source.id, set())
        if not source_tags:
            continue
        candidates: list[tuple[int, str, set[str]]] = []
        for target in documents[index + 1 :]:
            shared = source_tags & tag_ids_by_document.get(target.id, set())
            if shared:
                candidates.append((len(shared), target.id, shared))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        for weight, target_id, shared in candidates[:5]:
            edges.append(
                {
                    "id": f"{source.id}:{target_id}",
                    "sourceDocumentId": source.id,
                    "targetDocumentId": target_id,
                    "sharedTagIds": sorted(shared),
                    "weight": weight,
                }
            )
    return {
        "nodes": [
            {
                "id": item.id,
                "title": item.title,
                "researchedAt": item.researched_at,
                "tags": tags_by_document.get(item.id, []),
            }
            for item in documents
        ],
        "edges": edges,
        "truncated": len(documents) >= 200,
    }


def space_payload(space: KnowledgeSpace) -> dict[str, object]:
    return {
        "id": space.id,
        "name": space.name,
        "purpose": space.purpose,
        "visibility": space.visibility,
        "settingsRevision": space.settings_revision,
        "projectIds": list(space.project_ids_json or []),
        "createdAt": space.created_at,
        "updatedAt": space.updated_at,
    }


def _document_title(conversation_title: str, body: str) -> str:
    normalized_conversation_title = " ".join(conversation_title.split()).strip()
    if normalized_conversation_title not in _GENERIC_TITLES:
        return normalized_conversation_title[:500]
    heading = _MARKDOWN_HEADING.search(body)
    if heading:
        return " ".join(heading.group(1).split())[:500]
    first_line = next((" ".join(line.split()) for line in body.splitlines() if line.strip()), "AI 답변")
    return first_line[:120]


def _citation_snapshot(metadata: Mapping[str, object]) -> list[dict[str, object]]:
    sources = metadata.get("sources", [])
    citations = metadata.get("citations", [])
    if not isinstance(sources, list):
        return []
    citation_by_source: dict[str, Mapping[str, object]] = {}
    if isinstance(citations, list):
        for citation in citations:
            if not isinstance(citation, Mapping):
                continue
            source_id = citation.get("sourceId", citation.get("source_id"))
            if isinstance(source_id, str):
                citation_by_source[source_id] = citation
    result: list[dict[str, object]] = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        source_id = source.get("sourceId")
        if not isinstance(source_id, str):
            continue
        citation = citation_by_source.get(source_id, {})
        result.append(
            {
                "sourceId": source_id,
                "title": str(source.get("title") or source.get("domain") or "출처"),
                "url": str(source.get("normalizedUrl") or source.get("originalUrl") or ""),
                "domain": str(source.get("domain") or ""),
                "excerpt": str(source.get("verbatimExcerpt") or ""),
                "evidenceKind": str(source.get("evidenceKind") or ""),
                "markerNumber": citation.get(
                    "markerNumber", citation.get("marker_number")
                ),
                "status": str(citation.get("status") or "reference_only"),
            }
        )
    return result


def _normalize_tag(value: str) -> str:
    return _TAG_SPACE.sub(" ", normalize("NFKC", value).casefold()).strip()


def _tag_candidates(db: Session, space_id: str) -> list[ExistingTagCandidate]:
    tags = list(
        db.scalars(
            select(KnowledgeTag)
            .where(KnowledgeTag.space_id == space_id, KnowledgeTag.status == "active")
            .order_by(KnowledgeTag.canonical_name, KnowledgeTag.id)
            .limit(200)
        )
    )
    aliases_by_tag: dict[str, list[str]] = {}
    if tags:
        for alias in db.scalars(
            select(KnowledgeTagAlias).where(
                KnowledgeTagAlias.tag_id.in_([tag.id for tag in tags])
            )
        ):
            aliases_by_tag.setdefault(alias.tag_id, []).append(alias.alias)
    return [
        ExistingTagCandidate(
            id=tag.id,
            canonical_name=tag.canonical_name,
            scope_note=tag.scope_note,
            aliases=tuple(aliases_by_tag.get(tag.id, [])),
        )
        for tag in tags
    ]


def _resolve_document_tags(
    db: Session,
    *,
    space_id: str,
    suggested_ids: tuple[str, ...],
    new_tags: tuple[NewTagSuggestion, ...],
) -> list[str]:
    valid_ids = set(
        db.scalars(
            select(KnowledgeTag.id).where(
                KnowledgeTag.space_id == space_id,
                KnowledgeTag.id.in_(suggested_ids),
                KnowledgeTag.status == "active",
            )
        )
    ) if suggested_ids else set()
    resolved = [tag_id for tag_id in suggested_ids if tag_id in valid_ids]
    for suggestion in new_tags:
        if len(resolved) >= MAX_DOCUMENT_TAGS:
            break
        normalized_name = _normalize_tag(suggestion.canonical_name)
        if not normalized_name:
            continue
        tag = db.scalar(
            select(KnowledgeTag).where(
                KnowledgeTag.space_id == space_id,
                KnowledgeTag.namespace == "topic",
                KnowledgeTag.normalized_name == normalized_name,
            )
        )
        if tag is None:
            alias_match = db.scalar(
                select(KnowledgeTag)
                .join(KnowledgeTagAlias, KnowledgeTagAlias.tag_id == KnowledgeTag.id)
                .where(
                    KnowledgeTag.space_id == space_id,
                    KnowledgeTagAlias.normalized_alias == normalized_name,
                )
                .order_by(KnowledgeTag.id)
                .limit(1)
            )
            tag = alias_match
        if tag is None:
            tag = KnowledgeTag(
                space_id=space_id,
                namespace="topic",
                canonical_name=" ".join(suggestion.canonical_name.split())[:160],
                normalized_name=normalized_name[:160],
                scope_note=" ".join(suggestion.scope_note.split())[:500],
                status="active",
            )
            db.add(tag)
            db.flush()
        for alias_value in suggestion.aliases:
            normalized_alias = _normalize_tag(alias_value)[:160]
            if not normalized_alias or normalized_alias == tag.normalized_name:
                continue
            if db.get(KnowledgeTagAlias, (tag.id, normalized_alias)) is None:
                db.add(
                    KnowledgeTagAlias(
                        tag_id=tag.id,
                        normalized_alias=normalized_alias,
                        alias=" ".join(alias_value.split())[:160],
                        language=None,
                    )
                )
        if tag.id not in resolved:
            resolved.append(tag.id)
    return resolved


def _document_tags(
    db: Session, document_ids: tuple[str, ...]
) -> dict[str, list[dict[str, str]]]:
    if not document_ids:
        return {}
    rows = db.execute(
        select(KnowledgeDocumentTag.document_id, KnowledgeTag)
        .join(KnowledgeTag, KnowledgeTag.id == KnowledgeDocumentTag.tag_id)
        .where(KnowledgeDocumentTag.document_id.in_(document_ids))
        .order_by(KnowledgeTag.canonical_name, KnowledgeTag.id)
    )
    result: dict[str, list[dict[str, str]]] = {}
    for document_id, tag in rows:
        result.setdefault(document_id, []).append(
            {
                "id": tag.id,
                "name": tag.canonical_name,
                "namespace": tag.namespace,
                "scopeNote": tag.scope_note,
            }
        )
    return result


__all__ = [
    "create_knowledge_space",
    "document_list_payload",
    "document_payload",
    "ensure_default_space",
    "knowledge_graph_payload",
    "list_knowledge_documents",
    "list_knowledge_spaces",
    "require_knowledge_document",
    "require_knowledge_space",
    "save_message_as_knowledge_document",
    "space_payload",
    "update_knowledge_space",
]
