from __future__ import annotations

import base64
from datetime import datetime

from sqlalchemy import case, func, or_, select, text, update
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from ..agent_frontends import DEFAULT_AGENT_FRONTEND
from ..api.errors import ApiProblem
from ..authorization import (
    conversation_access_query,
    require_conversation,
    require_project,
)
from ..models import (
    Conversation,
    Artifact,
    Attachment,
    Message,
    MessageReference,
    Project,
    Run,
    User,
    utc_now,
)
from ..runs.state import ACTIVE_STATUSES, sidebar_status


def _encode_cursor(is_favorite: bool, activity: datetime, conversation_id: str) -> str:
    value = f"{int(is_favorite)}|{activity.isoformat()}|{conversation_id}".encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[bool, datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        favorite, timestamp, conversation_id = (
            base64.urlsafe_b64decode(padded).decode().split("|", 2)
        )
        if favorite not in {"0", "1"}:
            raise ValueError("invalid favorite marker")
        return favorite == "1", datetime.fromisoformat(timestamp), conversation_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise ApiProblem(
            400, "invalid_cursor", "대화 목록 cursor가 올바르지 않습니다."
        ) from exc


def default_project(db: Session, user: User) -> Project:
    project = db.scalar(
        select(Project).where(
            Project.owner_user_id == user.id,
            Project.is_default.is_(True),
            Project.archived_at.is_(None),
        )
    )
    if project is None:
        raise ApiProblem(
            409, "default_project_missing", "기본 프로젝트를 찾을 수 없습니다."
        )
    return project


def create_conversation(
    db: Session, user: User, *, project_id: str | None, title: str
) -> Conversation:
    project = (
        require_project(db, user, project_id, write=True)
        if project_id
        else default_project(db, user)
    )
    conversation = Conversation(
        organization_id=user.organization_id,
        project_id=project.id,
        owner_user_id=user.id,
        title=title.strip(),
        agent_id=DEFAULT_AGENT_FRONTEND.agent_id,
        agent_version=DEFAULT_AGENT_FRONTEND.agent_version,
        revision=1,
    )
    db.add(conversation)
    db.flush()
    return conversation


def list_conversations(
    db: Session,
    user: User,
    *,
    project_id: str | None = None,
    title_query: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
) -> tuple[list[Conversation], str | None]:
    limit = max(1, min(limit, 100))
    query = conversation_access_query(user).where(Conversation.surface == "chat")
    if project_id:
        require_project(db, user, project_id)
        query = query.where(Conversation.project_id == project_id)
    if title_query is not None:
        tokens = title_query.casefold().split()
        for token in tokens:
            query = query.where(func.lower(Conversation.title).contains(token))
    if cursor:
        is_favorite, activity, conversation_id = _decode_cursor(cursor)
        later_in_group = or_(
            Conversation.last_activity_at < activity,
            (
                (Conversation.last_activity_at == activity)
                & (Conversation.id > conversation_id)
            ),
        )
        if is_favorite:
            query = query.where(
                or_(Conversation.is_favorite.is_(False), later_in_group)
            )
        else:
            query = query.where(Conversation.is_favorite.is_(False), later_in_group)

    rows = list(
        db.scalars(
            query.order_by(
                Conversation.is_favorite.desc(),
                Conversation.last_activity_at.desc(),
                Conversation.id,
            ).limit(limit + 1)
        )
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = (
        _encode_cursor(
            items[-1].is_favorite,
            items[-1].last_activity_at,
            items[-1].id,
        )
        if has_more and items
        else None
    )
    return items, next_cursor


def list_auto_delete_candidates(
    db: Session, *, older_than: datetime, limit: int = 100
) -> list[Conversation]:
    """Return inactive chat candidates while honoring the durable like protection."""
    return list(
        db.scalars(
            select(Conversation)
            .where(
                Conversation.surface == "chat",
                Conversation.status == "active",
                Conversation.deleted_at.is_(None),
                Conversation.is_liked.is_(False),
                Conversation.last_activity_at < older_than,
            )
            .order_by(Conversation.last_activity_at, Conversation.id)
            .limit(max(1, min(limit, 1000)))
        )
    )


def search_conversation_content(
    db: Session,
    user: User,
    *,
    query_text: str,
    project_id: str | None = None,
    limit: int = 30,
) -> tuple[list[Conversation], tuple[str, ...]]:
    tokens = tuple(query_text.casefold().split())
    if not tokens:
        return [], ()
    limit = max(1, min(limit, 100))
    query = conversation_access_query(user).where(Conversation.surface == "chat")
    if project_id:
        require_project(db, user, project_id)
        query = query.where(Conversation.project_id == project_id)
    fts_available = _sqlite_message_fts_available(db)
    for token in tokens:
        title_match = func.lower(Conversation.title).contains(token)
        candidate_ids = (
            _fts_conversation_ids(db, token)
            if fts_available and len(token) >= 3
            else None
        )
        if candidate_ids is not None:
            query = query.where(
                or_(
                    title_match,
                    Conversation.id.in_(candidate_ids),
                )
            )
        message_match = select(Message.conversation_id).where(
            Message.conversation_id == Conversation.id,
            func.lower(Message.canonical_text).contains(token),
        )
        query = query.where(
            or_(
                title_match,
                message_match.exists(),
            )
        )
    rows = list(
        db.scalars(
            query.order_by(Conversation.last_activity_at.desc(), Conversation.id).limit(
                limit
            )
        )
    )
    return rows, tokens


def _sqlite_message_fts_available(db: Session) -> bool:
    bind = db.get_bind()
    if bind.dialect.name != "sqlite":
        return False
    return bool(
        db.scalar(
            text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'message_search_fts'"
            )
        )
    )


def _fts_conversation_ids(db: Session, token: str) -> tuple[str, ...] | None:
    match_query = f'"{token.replace(chr(34), chr(34) * 2)}"'
    try:
        return tuple(
            str(conversation_id)
            for conversation_id in db.scalars(
                text(
                    "SELECT DISTINCT conversation_id FROM message_search_fts "
                    "WHERE message_search_fts MATCH :match_query"
                ),
                {"match_query": match_query},
            )
        )
    except DatabaseError:
        return None


def conversation_summary(db: Session, conversation: Conversation) -> dict[str, object]:
    active = db.scalar(
        select(Run)
        .where(Run.conversation_id == conversation.id, Run.status.in_(ACTIVE_STATUSES))
        .order_by(Run.created_at.desc())
        .limit(1)
    )
    latest = active or db.scalar(
        select(Run)
        .where(Run.conversation_id == conversation.id)
        .order_by(Run.created_at.desc())
        .limit(1)
    )
    return _conversation_summary_payload(conversation, active or latest, active)


def conversation_summaries(
    db: Session, conversations: list[Conversation]
) -> dict[str, dict[str, object]]:
    if not conversations:
        return {}
    conversation_ids = [conversation.id for conversation in conversations]
    ranked = (
        select(
            Run.conversation_id.label("conversation_id"),
            Run.id.label("run_id"),
            Run.status.label("status"),
            Run.last_sequence.label("last_sequence"),
            func.row_number()
            .over(
                partition_by=Run.conversation_id,
                order_by=(
                    case((Run.status.in_(ACTIVE_STATUSES), 0), else_=1),
                    Run.created_at.desc(),
                    Run.id.desc(),
                ),
            )
            .label("rank"),
        )
        .where(Run.conversation_id.in_(conversation_ids))
        .subquery()
    )
    selected = {
        str(conversation_id): (str(run_id), str(status), int(last_sequence))
        for conversation_id, run_id, status, last_sequence in db.execute(
            select(
                ranked.c.conversation_id,
                ranked.c.run_id,
                ranked.c.status,
                ranked.c.last_sequence,
            ).where(ranked.c.rank == 1)
        )
    }
    return {
        conversation.id: _conversation_summary_payload(
            conversation,
            selected.get(conversation.id),
            (
                selected[conversation.id]
                if conversation.id in selected
                and selected[conversation.id][1] in ACTIVE_STATUSES
                else None
            ),
        )
        for conversation in conversations
    }


def _conversation_summary_payload(
    conversation: Conversation,
    latest: Run | tuple[str, str, int] | None,
    active: Run | tuple[str, str, int] | None,
) -> dict[str, object]:
    latest_status = (
        latest.status if isinstance(latest, Run) else latest[1] if latest else None
    )
    latest_sequence = (
        latest.last_sequence if isinstance(latest, Run) else latest[2] if latest else 0
    )
    active_run_id = (
        active.id if isinstance(active, Run) else active[0] if active else None
    )
    return {
        "id": conversation.id,
        "project_id": conversation.project_id,
        "title": conversation.title,
        "is_favorite": conversation.is_favorite,
        "is_liked": conversation.is_liked,
        "last_run_status": sidebar_status(latest_status) if latest_status else None,
        "active_run_id": active_run_id,
        "last_sequence": latest_sequence,
        "revision": conversation.revision,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def update_conversation(
    db: Session,
    user: User,
    conversation_id: str,
    *,
    expected_revision: int | None,
    title: str | None = None,
    is_favorite: bool | None = None,
    is_liked: bool | None = None,
    archived: bool | None = None,
) -> Conversation:
    conversation = require_conversation(db, user, conversation_id, write=True)
    if expected_revision is not None and conversation.revision != expected_revision:
        raise ApiProblem(409, "revision_conflict", "다른 곳에서 대화가 변경되었습니다.")
    values: dict[str, object] = {
        "revision": conversation.revision + 1,
        "last_activity_at": utc_now(),
    }
    if title is not None:
        values["title"] = title.strip()
    if is_favorite is not None:
        values["is_favorite"] = is_favorite
    if is_liked is not None:
        values["is_liked"] = is_liked
    if archived is not None:
        values["status"] = "archived" if archived else "active"
    if expected_revision is None:
        for field_name, value in values.items():
            setattr(conversation, field_name, value)
        db.flush()
        return conversation

    result = db.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation.id,
            Conversation.revision == expected_revision,
            Conversation.deleted_at.is_(None),
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        current_revision = db.scalar(
            select(Conversation.revision).where(Conversation.id == conversation.id)
        )
        raise ApiProblem(
            409,
            "revision_conflict",
            "다른 곳에서 대화가 변경되었습니다.",
            details={"currentRevision": current_revision},
        )
    db.expire(conversation)
    db.refresh(conversation)
    return conversation


def move_conversation(
    db: Session, user: User, conversation_id: str, destination_project_id: str
) -> Conversation:
    conversation = require_conversation(db, user, conversation_id, write=True)
    destination = require_project(db, user, destination_project_id, write=True)
    if conversation.project_id == destination.id:
        return conversation
    active = db.scalar(
        select(Run.id).where(
            Run.conversation_id == conversation.id,
            Run.status.in_(ACTIVE_STATUSES | {"queued"}),
        )
    )
    if active:
        raise ApiProblem(
            409,
            "run_in_progress",
            "실행 중이거나 대기 중인 작업이 끝난 뒤 프로젝트를 이동해 주세요.",
        )
    db.execute(
        update(Attachment)
        .where(
            Attachment.conversation_id == conversation.id,
            Attachment.deleted_at.is_(None),
        )
        .values(project_id=destination.id)
        .execution_options(synchronize_session=False)
    )
    db.execute(
        update(Artifact)
        .where(
            Artifact.conversation_id == conversation.id,
            Artifact.deleted_at.is_(None),
        )
        .values(project_id=destination.id)
        .execution_options(synchronize_session=False)
    )
    conversation.project_id = destination.id
    conversation.revision += 1
    conversation.last_activity_at = utc_now()
    db.flush()
    return conversation


def branch_conversation(
    db: Session,
    user: User,
    conversation_id: str,
    *,
    anchor_message_id: str,
    title: str | None,
) -> Conversation:
    source = require_conversation(db, user, conversation_id)
    anchor = db.get(Message, anchor_message_id)
    if anchor is None or anchor.conversation_id != source.id:
        raise ApiProblem(404, "message_not_found", "분기할 메시지를 찾을 수 없습니다.")
    if anchor.status != "completed":
        raise ApiProblem(
            409,
            "message_not_completed",
            "완료된 메시지에서만 대화를 분기할 수 있습니다.",
        )

    source_messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == source.id)
            .order_by(Message.created_at, Message.id)
        )
    )
    try:
        anchor_index = next(
            index
            for index, message in enumerate(source_messages)
            if message.id == anchor.id
        )
    except (
        StopIteration
    ) as exc:  # Defensive: the ownership predicate above should prevent this.
        raise ApiProblem(
            404, "message_not_found", "분기할 메시지를 찾을 수 없습니다."
        ) from exc
    included = source_messages[: anchor_index + 1]

    branch = Conversation(
        organization_id=source.organization_id,
        project_id=source.project_id,
        owner_user_id=user.id,
        title=(title or f"{source.title} · 분기").strip(),
        visibility=source.visibility,
        agent_id=source.agent_id,
        agent_version=source.agent_version,
        revision=1,
        parent_conversation_id=source.id,
        branch_message_id=anchor.id,
        last_activity_at=utc_now(),
    )
    db.add(branch)
    db.flush()

    source_ids = [message.id for message in included]
    references_by_message: dict[str, list[MessageReference]] = {}
    if source_ids:
        for reference in db.scalars(
            select(MessageReference)
            .where(MessageReference.message_id.in_(source_ids))
            .order_by(MessageReference.created_at, MessageReference.id)
        ):
            references_by_message.setdefault(reference.message_id, []).append(reference)

    for source_message in included:
        metadata = dict(source_message.metadata_json or {})
        metadata.update(
            {
                "branchedFromConversationId": source.id,
                "branchedFromMessageId": source_message.id,
                "branchSourceRunId": source_message.run_id,
            }
        )
        cloned = Message(
            conversation_id=branch.id,
            run_id=None,
            author_user_id=(
                user.id
                if source_message.role == "user"
                else source_message.author_user_id
            ),
            role=source_message.role,
            status="completed",
            canonical_text=source_message.canonical_text,
            turn_index=source_message.turn_index,
            metadata_json=metadata,
        )
        db.add(cloned)
        db.flush()
        for reference in references_by_message.get(source_message.id, ()):
            db.add(
                MessageReference(
                    message_id=cloned.id,
                    kind=reference.kind,
                    reference_id=reference.reference_id,
                    version_or_digest=reference.version_or_digest,
                    token_start=reference.token_start,
                    token_end=reference.token_end,
                    display_snapshot_json=dict(reference.display_snapshot_json or {}),
                    validation_status=reference.validation_status,
                )
            )
    db.flush()
    return branch


def soft_delete_conversation(db: Session, user: User, conversation_id: str) -> None:
    conversation = require_conversation(db, user, conversation_id, write=True)
    active = db.scalar(
        select(Run.id).where(
            Run.conversation_id == conversation.id,
            Run.status.in_(ACTIVE_STATUSES | {"queued"}),
        )
    )
    if active:
        raise ApiProblem(409, "run_in_progress", "실행 중인 대화는 삭제할 수 없습니다.")
    conversation.deleted_at = utc_now()
    conversation.status = "deleted"
    conversation.revision += 1
    db.flush()


def recent_messages(
    db: Session, conversation_id: str, limit: int = 100
) -> list[Message]:
    rows = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
    )
    rows.reverse()
    return rows
