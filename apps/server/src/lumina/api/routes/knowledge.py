from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...db import get_db
from ...config import Settings, get_settings
from ...knowledge.executor import knowledge_ingestion_executor
from ...knowledge.schemas import (
    KnowledgeAutoCaptureUpdate,
    KnowledgeEntityCreate,
    KnowledgePageUpdate,
    KnowledgeProjectBindingCreate,
    KnowledgeProjectBindingUpdate,
    KnowledgeSourceCreate,
    KnowledgeSpaceCreate,
    KnowledgeSpaceUpdate,
    KnowledgeReviewDecision,
    KnowledgeStatementCreate,
)
from ...knowledge.service import (
    archive_knowledge_space,
    create_knowledge_project_binding,
    create_knowledge_entity,
    create_knowledge_ingestion_job,
    create_knowledge_source,
    create_knowledge_space,
    create_knowledge_statement,
    decide_knowledge_statement,
    delete_knowledge_project_binding,
    entity_payload,
    ingestion_job_payload,
    knowledge_auto_capture_payload,
    knowledge_page_payload,
    knowledge_page_revision_payload,
    knowledge_project_binding_payload,
    knowledge_revision_payload,
    knowledge_neighborhood,
    list_knowledge_entities,
    list_knowledge_ingestion_jobs,
    list_knowledge_page_revisions,
    list_knowledge_pages,
    list_knowledge_project_bindings,
    list_knowledge_revisions,
    list_knowledge_sources,
    list_knowledge_spaces,
    list_knowledge_statements,
    require_knowledge_space,
    source_payload,
    space_payload,
    statement_payload,
    update_knowledge_space,
    update_knowledge_auto_capture,
    update_knowledge_page,
    update_knowledge_project_binding,
)
from ...models import User
from ..dependencies import AuthContext, get_current_user, require_csrf


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/auto-capture")
def get_knowledge_auto_capture(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return knowledge_auto_capture_payload(db, user)


@router.patch("/auto-capture")
def patch_knowledge_auto_capture(
    payload: KnowledgeAutoCaptureUpdate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    updated = update_knowledge_auto_capture(db, context.user, payload)
    record_audit(
        db,
        action="knowledge_auto_capture_updated",
        target_type="knowledge_space",
        target_id=updated.get("spaceId"),
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"enabled": updated["enabled"], "mode": updated["mode"]},
    )
    db.commit()
    return updated


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


@router.patch("/spaces/{space_id}")
def patch_knowledge_space(
    space_id: str,
    payload: KnowledgeSpaceUpdate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    space = update_knowledge_space(db, context.user, space_id, payload)
    record_audit(
        db,
        action="knowledge_space_updated",
        target_type="knowledge_space",
        target_id=space.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"settings_revision": space.settings_revision},
    )
    db.commit()
    return space_payload(space)


@router.delete("/spaces/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge_space(
    space_id: str,
    request: Request,
    expected_revision: int = Query(alias="expectedRevision", ge=1),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    space = archive_knowledge_space(
        db,
        context.user,
        space_id,
        expected_revision=expected_revision,
    )
    record_audit(
        db,
        action="knowledge_space_archived",
        target_type="knowledge_space",
        target_id=space.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@router.post(
    "/spaces/{space_id}/sources/{source_id}/ingestions",
    status_code=status.HTTP_202_ACCEPTED,
)
def post_knowledge_ingestion(
    space_id: str,
    source_id: str,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    job, created = create_knowledge_ingestion_job(
        db,
        context.user,
        space_id,
        source_id,
        settings=settings,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    record_audit(
        db,
        action=(
            "knowledge_ingestion_queued" if created else "knowledge_ingestion_reused"
        ),
        target_type="knowledge_ingestion_job",
        target_id=job.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "source_id": source_id,
            "provider_id": job.provider_id,
            "model_key": job.model_key,
        },
    )
    db.commit()
    if created:
        knowledge_ingestion_executor.enqueue(job.id)
    return ingestion_job_payload(job)


@router.get("/spaces/{space_id}/ingestions")
def get_knowledge_ingestions(
    space_id: str,
    source_id: str | None = Query(default=None, alias="sourceId"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        ingestion_job_payload(job)
        for job in list_knowledge_ingestion_jobs(
            db, user, space_id, source_id=source_id
        )
    ]


@router.get("/spaces/{space_id}/pages")
def get_knowledge_pages(
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        knowledge_page_payload(page, revision, revision_count)
        for page, revision, revision_count in list_knowledge_pages(
            db, user, space_id
        )
    ]


@router.get("/spaces/{space_id}/revisions")
def get_knowledge_revisions(
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        knowledge_revision_payload(revision)
        for revision in list_knowledge_revisions(db, user, space_id)
    ]


@router.get("/spaces/{space_id}/project-bindings")
def get_knowledge_project_bindings(
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        knowledge_project_binding_payload(db, binding)
        for binding in list_knowledge_project_bindings(db, user, space_id)
    ]


@router.post("/spaces/{space_id}/project-bindings", status_code=201)
def post_knowledge_project_binding(
    space_id: str,
    payload: KnowledgeProjectBindingCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    binding = create_knowledge_project_binding(db, context.user, space_id, payload)
    record_audit(
        db,
        action="knowledge_project_binding_created",
        target_type="knowledge_project_binding",
        target_id=binding.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "project_id": binding.project_id,
            "space_id": binding.space_id,
            "knowledge_revision_id": binding.knowledge_revision_id,
            "permission": binding.permission,
        },
    )
    db.commit()
    return knowledge_project_binding_payload(db, binding)


@router.patch("/project-bindings/{binding_id}")
def patch_knowledge_project_binding(
    binding_id: str,
    payload: KnowledgeProjectBindingUpdate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    binding = update_knowledge_project_binding(
        db, context.user, binding_id, payload
    )
    record_audit(
        db,
        action="knowledge_project_binding_updated",
        target_type="knowledge_project_binding",
        target_id=binding.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "project_id": binding.project_id,
            "space_id": binding.space_id,
            "knowledge_revision_id": binding.knowledge_revision_id,
            "binding_revision": binding.binding_revision,
        },
    )
    db.commit()
    return knowledge_project_binding_payload(db, binding)


@router.delete("/project-bindings/{binding_id}", status_code=204)
def delete_knowledge_project_binding_route(
    binding_id: str,
    request: Request,
    expected_revision: int = Query(ge=1, alias="expectedRevision"),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    binding = delete_knowledge_project_binding(
        db,
        context.user,
        binding_id,
        expected_revision=expected_revision,
    )
    record_audit(
        db,
        action="knowledge_project_binding_deleted",
        target_type="knowledge_project_binding",
        target_id=binding.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "project_id": binding.project_id,
            "space_id": binding.space_id,
            "knowledge_revision_id": binding.knowledge_revision_id,
        },
    )
    db.commit()
    return Response(status_code=204)


@router.get("/pages/{page_id}/revisions")
def get_knowledge_page_revisions(
    page_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _page, revisions = list_knowledge_page_revisions(db, user, page_id)
    return [knowledge_page_revision_payload(revision) for revision in revisions]


@router.patch("/pages/{page_id}")
def patch_knowledge_page(
    page_id: str,
    payload: KnowledgePageUpdate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    page, revision, revision_count = update_knowledge_page(
        db, context.user, page_id, payload
    )
    record_audit(
        db,
        action="knowledge_page_updated",
        target_type="knowledge_page",
        target_id=page.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"revision_number": revision.revision_number},
    )
    db.commit()
    return knowledge_page_payload(page, revision, revision_count)


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


@router.post("/reviews/{statement_id}/decision")
def post_knowledge_review_decision(
    statement_id: str,
    payload: KnowledgeReviewDecision,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    statement = decide_knowledge_statement(db, context.user, statement_id, payload)
    record_audit(
        db,
        action="knowledge_statement_reviewed",
        target_type="knowledge_statement",
        target_id=statement.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "decision": statement.status,
            "revision_id": statement.revision_id,
            "supersedes_statement_id": statement.supersedes_statement_id,
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
