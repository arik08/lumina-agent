from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...db import get_db
from ...config import Settings, get_settings
from ...memories.schemas import MemoryCreate, MemoryPatch, MemorySettingsPatch
from ...memories.service import (
    create_memory,
    delete_memory,
    get_memory_setting,
    list_memories,
    memory_payload,
    optimize_memories_with_llm,
    patch_memory,
    set_memory_setting,
)
from ...models import ProviderModel, User
from ...providers.codex import CodexResponsesAdapter
from ..errors import ApiProblem
from ..dependencies import AuthContext, get_current_user, require_csrf


router = APIRouter(tags=["memories"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/memories")
def get_memories(
    status: Literal["active", "pending", "dismissed", "superseded"] = "active",
    query: str | None = Query(default=None, max_length=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        memory_payload(item)
        for item in list_memories(db, user=user, status=status, query=query)
    ]


@router.post("/memories", status_code=201)
def post_memory(
    payload: MemoryCreate,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    memory, created = create_memory(
        db,
        user=context.user,
        category=payload.category,
        fact=payload.fact,
        display_text=payload.display_text,
        source_message_ids=payload.source_message_ids,
        confidence=payload.confidence,
        expires_at=payload.expires_at,
    )
    if not created:
        response.status_code = 200
    record_audit(
        db,
        action="memory_created" if created else "memory_confirmed",
        target_type="user_memory",
        target_id=memory.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={
            "category": memory.category,
            "evidence_count": memory.evidence_count,
            "source_message_count": len(memory.source_message_ids_json),
        },
    )
    db.commit()
    return memory_payload(memory)


@router.post("/memories/optimize")
async def optimize_user_memories(
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    api_key = settings.openai_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        raise ApiProblem(503, "memory_optimizer_unavailable", "Codex LLM 설정이 필요합니다.")
    model = db.scalar(
        select(ProviderModel).where(
            ProviderModel.provider_id == "codex",
            ProviderModel.enabled.is_(True),
            ProviderModel.is_default.is_(True),
        )
    )
    if model is None:
        raise ApiProblem(503, "memory_optimizer_unavailable", "활성 Codex 기본 Model이 없습니다.")
    result = await optimize_memories_with_llm(
        db,
        user=context.user,
        provider=CodexResponsesAdapter(
            api_key=api_key.get_secret_value(),
            base_url=settings.openai_base_url,
        ),
        model=model.runtime_model_id,
    )
    record_audit(
        db,
        action="memories_optimized",
        target_type="user_memory",
        target_id=context.user.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"merged_ids": list(result.merged_ids), "superseded_ids": list(result.superseded_ids), "model": model.runtime_model_id},
    )
    db.commit()
    return {"mergedIds": list(result.merged_ids), "supersededIds": list(result.superseded_ids)}


@router.patch("/memories/{memory_id}")
def patch_user_memory(
    memory_id: str,
    payload: MemoryPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True, by_alias=False)
    memory = patch_memory(
        db,
        user=context.user,
        memory_id=memory_id,
        changes=changes,
    )
    record_audit(
        db,
        action="memory_edited",
        target_type="user_memory",
        target_id=memory.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"changed_fields": sorted(changes), "status": memory.status},
    )
    db.commit()
    return memory_payload(memory)


@router.delete("/memories/{memory_id}", status_code=204)
def delete_user_memory(
    memory_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    memory = delete_memory(db, user=context.user, memory_id=memory_id)
    record_audit(
        db,
        action="memory_deleted",
        target_type="user_memory",
        target_id=memory.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
    )
    db.commit()
    return Response(status_code=204)


@router.get("/memory-settings")
def get_memory_settings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    mode, _setting = get_memory_setting(db, user)
    return {"mode": mode, "enabled": mode != "off"}


@router.patch("/memory-settings")
def patch_memory_settings(
    payload: MemorySettingsPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    mode = payload.mode
    if mode is None:
        mode = "auto" if payload.enabled else "off"
    setting = set_memory_setting(db, user=context.user, mode=mode)
    record_audit(
        db,
        action="memory_settings_changed",
        target_type="user_setting",
        target_id=setting.id,
        result="success",
        actor=context.user,
        request_id=_request_id(request),
        metadata={"mode": mode},
    )
    db.commit()
    return {"mode": mode, "enabled": mode != "off"}
