from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from ...agent.executor import local_run_executor
from ...audit import record_audit
from ...authorization import require_project
from ...db import get_db
from ...knowledge.schemas import KnowledgeSpaceCreate, KnowledgeSpaceUpdate
from ...knowledge.service import (
    create_knowledge_space,
    document_list_payload,
    document_payload,
    knowledge_graph_payload,
    list_knowledge_documents,
    list_knowledge_spaces,
    require_knowledge_document,
    save_message_as_knowledge_document,
    space_payload,
    update_knowledge_space,
)
from ...models import User
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


@router.get("/documents")
def get_knowledge_documents(
    space_id: str | None = Query(default=None, alias="spaceId"),
    project_id: str | None = Query(default=None, alias="projectId"),
    query: str = Query(default="", max_length=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    if project_id:
        require_project(db, user, project_id)
    documents = list_knowledge_documents(
        db, user, space_id=space_id, project_id=project_id, query=query
    )
    return document_list_payload(db, documents)


@router.get("/documents/{document_id}")
def get_knowledge_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return document_payload(db, require_knowledge_document(db, user, document_id))


@router.post("/documents/from-message/{message_id}")
async def post_knowledge_document_from_message(
    message_id: str,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    document, created = await save_message_as_knowledge_document(
        db,
        context.user,
        message_id,
        provider_factory=local_run_executor.provider_for_probe,
    )
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


@router.get("/graph")
def get_knowledge_graph(
    space_id: str | None = Query(default=None, alias="spaceId"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return knowledge_graph_payload(db, user, space_id=space_id)
