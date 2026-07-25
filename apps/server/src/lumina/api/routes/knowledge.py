from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...agent.executor import local_run_executor
from ...audit import record_audit
from ...authorization import require_project
from ...db import get_db
from ...config import Settings, get_settings
from ...knowledge.schemas import (
    KnowledgeBatchTagRequest,
    KnowledgeDocumentTagsUpdate,
    KnowledgeSpaceCreate,
    KnowledgeSpaceUpdate,
    KnowledgeTagCreate,
    KnowledgeTagProposalBatchResolve,
    KnowledgeTagProposalResolve,
    KnowledgeTagUpdate,
)
from ...knowledge.service import (
    create_knowledge_space,
    create_knowledge_tag,
    delete_knowledge_document,
    document_list_payload,
    document_payload,
    knowledge_graph_payload,
    knowledge_tag_proposal_payload,
    knowledge_tag_payloads,
    list_knowledge_documents,
    list_knowledge_spaces,
    list_knowledge_tags,
    list_knowledge_tag_proposals,
    require_knowledge_document,
    resolve_knowledge_tag_proposal,
    resolve_knowledge_tag_proposals,
    save_message_as_knowledge_document,
    space_payload,
    tag_untagged_knowledge_documents,
    update_knowledge_space,
    update_knowledge_document_tags,
    update_knowledge_tag,
)
from ...models import ProviderModel, User
from ..errors import ApiProblem
from ..dependencies import AuthContext, get_current_user, require_csrf


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/spaces")
def get_knowledge_spaces(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict[str, object]]:
    return [space_payload(item) for item in list_knowledge_spaces(db, user)]


@router.post("/spaces", status_code=status.HTTP_201_CREATED)
def post_knowledge_space(
    payload: KnowledgeSpaceCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    space = create_knowledge_space(db, context.user, payload)
    record_audit(
        db,
        action="knowledge_space_created",
        target_type="knowledge_space",
        target_id=space.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    db.refresh(space)
    return space_payload(space)


@router.patch("/spaces/{space_id}")
def patch_knowledge_space(
    space_id: str,
    payload: KnowledgeSpaceUpdate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    space = update_knowledge_space(db, context.user, space_id, payload)
    record_audit(
        db,
        action="knowledge_space_updated",
        target_type="knowledge_space",
        target_id=space.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    db.refresh(space)
    return space_payload(space)


@router.get("/tags")
def get_knowledge_tags(
    space_id: str = Query(alias="spaceId"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    return knowledge_tag_payloads(
        db, list_knowledge_tags(db, user, space_id=space_id)
    )


@router.get("/tag-proposals")
def get_knowledge_tag_proposals(
    space_id: str = Query(alias="spaceId"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    return [
        knowledge_tag_proposal_payload(item)
        for item in list_knowledge_tag_proposals(db, user, space_id=space_id)
    ]


@router.post("/tag-proposals/resolve-batch")
def post_knowledge_tag_proposal_batch_resolution(
    payload: KnowledgeTagProposalBatchResolve,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    proposals = resolve_knowledge_tag_proposals(
        db,
        context.user,
        payload.proposal_ids,
        action=payload.action,
    )
    record_audit(
        db,
        action=f"knowledge_tag_proposals_{payload.action}",
        target_type="knowledge_tag_proposal",
        target_id=proposals[0].id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"count": len(proposals), "proposal_ids": payload.proposal_ids},
    )
    db.commit()
    return {"resolvedCount": len(proposals)}


@router.post("/tag-proposals/{proposal_id}/resolve")
def post_knowledge_tag_proposal_resolution(
    proposal_id: str,
    payload: KnowledgeTagProposalResolve,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    proposal = resolve_knowledge_tag_proposal(
        db,
        context.user,
        proposal_id,
        action=payload.action,
        expected_revision=payload.expected_revision,
        target_tag_id=payload.target_tag_id,
    )
    record_audit(
        db,
        action=f"knowledge_tag_proposal_{payload.action}",
        target_type="knowledge_tag_proposal",
        target_id=proposal.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"resolved_tag_id": proposal.resolved_tag_id},
    )
    db.commit()
    return knowledge_tag_proposal_payload(proposal)


@router.post("/tags", status_code=status.HTTP_201_CREATED)
def post_knowledge_tag(
    payload: KnowledgeTagCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    tag = create_knowledge_tag(db, context.user, payload)
    record_audit(
        db,
        action="knowledge_tag_created",
        target_type="knowledge_tag",
        target_id=tag.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"space_id": tag.space_id, "namespace": tag.namespace},
    )
    db.commit()
    db.refresh(tag)
    return knowledge_tag_payloads(db, [tag])[0]


@router.patch("/tags/{tag_id}")
def patch_knowledge_tag(
    tag_id: str,
    payload: KnowledgeTagUpdate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    tag = update_knowledge_tag(db, context.user, tag_id, payload)
    record_audit(
        db,
        action="knowledge_tag_updated",
        target_type="knowledge_tag",
        target_id=tag.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"space_id": tag.space_id, "namespace": tag.namespace},
    )
    db.commit()
    db.refresh(tag)
    return knowledge_tag_payloads(db, [tag])[0]


@router.get("/documents")
def get_knowledge_documents(
    space_id: str | None = Query(default=None, alias="spaceId"),
    project_id: str | None = Query(default=None, alias="projectId"),
    query: str = Query(default="", max_length=500),
    limit: int | None = Query(default=None, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    if project_id:
        require_project(db, user, project_id)
    documents = list_knowledge_documents(
        db,
        user,
        space_id=space_id,
        project_id=project_id,
        query=query,
        limit=limit,
    )
    return document_list_payload(db, documents)


@router.get("/documents/{document_id}")
def get_knowledge_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return document_payload(db, require_knowledge_document(db, user, document_id))


@router.patch("/documents/{document_id}")
def patch_knowledge_document_tags(
    document_id: str,
    payload: KnowledgeDocumentTagsUpdate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    document = update_knowledge_document_tags(
        db, context.user, document_id, payload
    )
    record_audit(
        db,
        action="knowledge_document_tags_updated",
        target_type="knowledge_document",
        target_id=document.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"space_id": document.space_id, "tag_count": len(payload.tags)},
    )
    db.commit()
    return document_payload(db, document)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_knowledge_document(
    document_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    document = delete_knowledge_document(db, context.user, document_id)
    record_audit(
        db,
        action="knowledge_document_deleted",
        target_type="knowledge_document",
        target_id=document.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"space_id": document.space_id, "project_id": document.project_id},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/documents/from-message/{message_id}")
def post_knowledge_document_from_message(
    message_id: str,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    document, created = save_message_as_knowledge_document(db, context.user, message_id)
    record_audit(
        db,
        action="knowledge_document_saved" if created else "knowledge_document_reused",
        target_type="knowledge_document",
        target_id=document.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"message_id": message_id},
    )
    db.commit()
    db.refresh(document)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return {**document_payload(db, document), "created": created}


@router.post("/documents/tag-batch")
async def post_knowledge_document_batch_tags(
    payload: KnowledgeBatchTagRequest,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    if payload.provider_id == "mock":
        if settings.environment == "production" or payload.model_key != "mock-agent":
            raise ApiProblem(
                409, "provider_unavailable", "사용 가능한 태깅 모델이 아닙니다."
            )
        runtime_model_id = "mock-agent"
    else:
        model = db.scalar(
            select(ProviderModel).where(
                ProviderModel.provider_id == payload.provider_id,
                ProviderModel.model_key == payload.model_key,
                ProviderModel.enabled.is_(True),
            )
        )
        if model is None:
            raise ApiProblem(
                409, "provider_unavailable", "사용 가능한 태깅 모델이 아닙니다."
            )
        runtime_model_id = model.runtime_model_id
    result = await tag_untagged_knowledge_documents(
        db,
        context.user,
        space_id=payload.space_id,
        provider=local_run_executor.provider_for_probe(payload.provider_id),
        model=runtime_model_id,
        provider_id=payload.provider_id,
        model_key=payload.model_key,
        target=payload.target,
        new_tag_policy=payload.new_tag_policy,
    )
    record_audit(
        db,
        action="knowledge_documents_batch_tagged",
        target_type="knowledge_space",
        target_id=payload.space_id,
        result="success" if result["failedCount"] == 0 else "partial",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={
            "provider_id": payload.provider_id,
            "model_key": payload.model_key,
            **result,
        },
    )
    db.commit()
    return result


@router.get("/graph")
def get_knowledge_graph(
    space_id: str | None = Query(default=None, alias="spaceId"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return knowledge_graph_payload(db, user, space_id=space_id)
