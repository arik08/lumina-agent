from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...db import get_db
from ...knowledge.schemas import (
    KnowledgeEntityCreate,
    KnowledgeSourceCreate,
    KnowledgeSpaceCreate,
    KnowledgeStatementCreate,
)
from ...knowledge.service import (
    create_knowledge_entity,
    create_knowledge_source,
    create_knowledge_space,
    create_knowledge_statement,
    entity_payload,
    knowledge_neighborhood,
    list_knowledge_entities,
    list_knowledge_sources,
    list_knowledge_spaces,
    list_knowledge_statements,
    require_knowledge_space,
    source_payload,
    space_payload,
    statement_payload,
)
from ...models import User
from ..dependencies import AuthContext, get_current_user, require_csrf


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/spaces")
def get_knowledge_spaces(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [space_payload(space) for space in list_knowledge_spaces(db, user)]


@router.post("/spaces", status_code=201)
def post_knowledge_space(
    payload: KnowledgeSpaceCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    space = create_knowledge_space(db, context.user, payload)
    record_audit(
        db,
        action="knowledge_space_created",
        target_type="knowledge_space",
        target_id=space.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return space_payload(space)


@router.get("/spaces/{space_id}")
def get_knowledge_space(
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return space_payload(require_knowledge_space(db, user, space_id))


@router.post("/spaces/{space_id}/sources", status_code=201)
def post_knowledge_source(
    space_id: str,
    payload: KnowledgeSourceCreate,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    source, revision, evidence, created = create_knowledge_source(
        db, context.user, space_id, payload
    )
    if not created:
        response.status_code = 200
    record_audit(
        db,
        action="knowledge_source_created"
        if created
        else "knowledge_source_deduplicated",
        target_type="knowledge_source",
        target_id=source.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"revision_id": revision.id, "evidence_count": len(evidence)},
    )
    db.commit()
    return source_payload(source, revision, evidence)


@router.get("/spaces/{space_id}/sources")
def get_knowledge_sources(
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        source_payload(source, revision, evidence)
        for source, revision, evidence in list_knowledge_sources(db, user, space_id)
    ]


@router.post("/spaces/{space_id}/entities", status_code=201)
def post_knowledge_entity(
    space_id: str,
    payload: KnowledgeEntityCreate,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    entity, created = create_knowledge_entity(db, context.user, space_id, payload)
    if not created:
        response.status_code = 200
    record_audit(
        db,
        action="knowledge_entity_created" if created else "knowledge_entity_reused",
        target_type="knowledge_entity",
        target_id=entity.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return entity_payload(entity)


@router.get("/spaces/{space_id}/entities")
def get_knowledge_entities(
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        entity_payload(entity) for entity in list_knowledge_entities(db, user, space_id)
    ]


@router.get("/spaces/{space_id}/statements")
def get_knowledge_statements(
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        statement_payload(db, statement)
        for statement in list_knowledge_statements(db, user, space_id)
    ]


@router.post("/spaces/{space_id}/statements", status_code=201)
def post_knowledge_statement(
    space_id: str,
    payload: KnowledgeStatementCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    statement = create_knowledge_statement(db, context.user, space_id, payload)
    record_audit(
        db,
        action="knowledge_statement_created",
        target_type="knowledge_statement",
        target_id=statement.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "revision_id": statement.revision_id,
            "status": statement.status,
        },
    )
    db.commit()
    return statement_payload(db, statement)


@router.get("/entities/{entity_id}/neighborhood")
def get_knowledge_neighborhood(
    entity_id: str,
    max_depth: int = Query(default=1, alias="maxDepth", ge=1, le=3),
    max_nodes: int = Query(default=100, alias="maxNodes", ge=1, le=500),
    max_edges: int = Query(default=200, alias="maxEdges", ge=1, le=1_000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return knowledge_neighborhood(
        db,
        user,
        entity_id,
        max_depth=max_depth,
        max_nodes=max_nodes,
        max_edges=max_edges,
    )
