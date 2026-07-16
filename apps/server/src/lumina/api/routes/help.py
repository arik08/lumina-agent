from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...authorization import require_admin
from ...db import get_db
from ...models import HelpItem, User, new_uuid
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem
from ..schemas import ApiModel


router = APIRouter(prefix="/help", tags=["help"])
ROOT_SCOPE_KEY = "__root__"


class HelpItemCreate(ApiModel):
    kind: Literal["folder", "document"]
    title: str = Field(min_length=1, max_length=160)
    parent_id: str | None = None
    markdown_content: str = Field(default="", max_length=1_000_000)


class HelpItemUpdate(ApiModel):
    title: str = Field(min_length=1, max_length=160)
    markdown_content: str = Field(default="", max_length=1_000_000)
    expected_revision: int = Field(ge=1)


def _title(value: str) -> str:
    title = " ".join(value.strip().split())
    if not title:
        raise ApiProblem(422, "help_title_required", "이름을 입력해 주세요.")
    return title


def _payload(item: HelpItem) -> dict[str, object]:
    return {
        "id": item.id,
        "parentId": item.parent_id,
        "kind": item.kind,
        "title": item.title,
        "markdownContent": item.markdown_content,
        "sortOrder": item.sort_order,
        "revision": item.revision,
        "createdByUserId": item.created_by_user_id,
        "updatedByUserId": item.updated_by_user_id,
        "createdAt": item.created_at,
        "updatedAt": item.updated_at,
    }


def _item(db: Session, user: User, item_id: str) -> HelpItem:
    item = db.scalar(
        select(HelpItem).where(
            HelpItem.id == item_id,
            HelpItem.organization_id == user.organization_id,
        )
    )
    if item is None:
        raise ApiProblem(404, "help_item_not_found", "안내 항목을 찾을 수 없습니다.")
    return item


def _parent(db: Session, user: User, parent_id: str | None) -> HelpItem | None:
    if parent_id is None:
        return None
    parent = _item(db, user, parent_id)
    if parent.kind != "folder":
        raise ApiProblem(422, "help_parent_not_folder", "폴더 안에만 항목을 만들 수 있습니다.")
    return parent


def _next_sort_order(db: Session, user: User, parent_id: str | None) -> int:
    siblings = list(
        db.scalars(
            select(HelpItem.sort_order).where(
                HelpItem.organization_id == user.organization_id,
                HelpItem.parent_scope_key == (parent_id or ROOT_SCOPE_KEY),
            )
        )
    )
    return max(siblings, default=-1) + 1


def _update_help_item_record(
    db: Session,
    user: User,
    item_id: str,
    *,
    title: str,
    markdown_content: str,
    expected_revision: int,
) -> HelpItem:
    item = _item(db, user, item_id)
    if item.revision != expected_revision:
        raise ApiProblem(
            409,
            "help_revision_conflict",
            "다른 관리자가 먼저 수정했습니다. 새로 고침 후 다시 시도해 주세요.",
        )
    normalized_title = _title(title)
    result = db.execute(
        update(HelpItem)
        .where(
            HelpItem.id == item.id,
            HelpItem.organization_id == user.organization_id,
            HelpItem.revision == expected_revision,
        )
        .values(
            title=normalized_title,
            title_key=normalized_title.casefold(),
            markdown_content=markdown_content if item.kind == "document" else "",
            revision=expected_revision + 1,
            updated_by_user_id=user.id,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        db.expire(item)
        db.refresh(item)
        raise ApiProblem(
            409,
            "help_revision_conflict",
            "다른 관리자가 먼저 수정했습니다. 새로 고침 후 다시 시도해 주세요.",
        )
    db.expire(item)
    db.refresh(item)
    return item


@router.get("/items")
def list_help_items(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    items = list(
        db.scalars(
            select(HelpItem)
            .where(HelpItem.organization_id == user.organization_id)
            .order_by(HelpItem.sort_order, HelpItem.kind, HelpItem.title_key)
        )
    )
    return {"items": [_payload(item) for item in items], "canManage": user.role == "admin"}


@router.post("/items", status_code=201)
def create_help_item(
    payload: HelpItemCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(context.user)
    parent = _parent(db, context.user, payload.parent_id)
    title = _title(payload.title)
    item = HelpItem(
        id=new_uuid(),
        organization_id=context.user.organization_id,
        parent_id=parent.id if parent else None,
        parent_scope_key=parent.id if parent else ROOT_SCOPE_KEY,
        kind=payload.kind,
        title=title,
        title_key=title.casefold(),
        markdown_content=payload.markdown_content if payload.kind == "document" else "",
        sort_order=_next_sort_order(db, context.user, parent.id if parent else None),
        created_by_user_id=context.user.id,
        updated_by_user_id=context.user.id,
    )
    db.add(item)
    record_audit(
        db,
        action="help_item_created",
        target_type="help_item",
        target_id=item.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"kind": item.kind, "title": item.title, "parent_id": item.parent_id},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiProblem(409, "help_title_conflict", "같은 위치에 같은 이름이 이미 있습니다.") from exc
    db.refresh(item)
    return _payload(item)


@router.patch("/items/{item_id}")
def update_help_item(
    item_id: str,
    payload: HelpItemUpdate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_admin(context.user)
    try:
        item = _update_help_item_record(
            db,
            context.user,
            item_id,
            title=payload.title,
            markdown_content=payload.markdown_content,
            expected_revision=payload.expected_revision,
        )
        record_audit(
            db,
            action="help_item_updated",
            target_type="help_item",
            target_id=item.id,
            result="success",
            actor=context.user,
            request_id=getattr(request.state, "request_id", None),
            metadata={
                "kind": item.kind,
                "title": item.title,
                "revision": item.revision,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiProblem(409, "help_title_conflict", "같은 위치에 같은 이름이 이미 있습니다.") from exc
    db.refresh(item)
    return _payload(item)


@router.delete("/items/{item_id}", status_code=204)
def delete_help_item(
    item_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    require_admin(context.user)
    item = _item(db, context.user, item_id)
    descendants: list[HelpItem] = []
    frontier = [item.id]
    while frontier:
        children = list(
            db.scalars(
                select(HelpItem).where(
                    HelpItem.organization_id == context.user.organization_id,
                    HelpItem.parent_id.in_(frontier),
                )
            )
        )
        descendants.extend(children)
        frontier = [child.id for child in children]
    record_audit(
        db,
        action="help_item_deleted",
        target_type="help_item",
        target_id=item.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"kind": item.kind, "title": item.title, "descendant_count": len(descendants)},
    )
    for descendant in reversed(descendants):
        db.delete(descendant)
    db.flush()
    db.delete(item)
    db.commit()
    return Response(status_code=204)
