from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...auth.security import generate_secret_token, hash_token
from ...config import Settings, get_settings
from ...db import get_db
from ...models import (
    Artifact,
    ArtifactVersion,
    Attachment,
    Conversation,
    ConversationShareGrant,
    Message,
    User,
    utc_now,
)
from ...storage import ManagedLocalStorage, StorageNotFoundError
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem
from ..schemas import ShareCreate


router = APIRouter(prefix="/conversation-shares", tags=["conversation-sharing"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _not_found() -> ApiProblem:
    # Do not distinguish a nonexistent token, wrong recipient, revoked grant,
    # expired grant, or deleted source conversation.
    return ApiProblem(404, "share_not_found", "공유된 대화를 찾을 수 없습니다.")


def _share_payload(
    grant: ConversationShareGrant,
    *,
    recipient: User | None = None,
) -> dict[str, object]:
    return {
        "id": grant.id,
        "conversationId": grant.conversation_id,
        "recipient": (
            {
                "id": recipient.id,
                "loginId": recipient.login_id,
                "displayName": recipient.display_name,
            }
            if recipient is not None
            else None
        ),
        "scope": grant.scope,
        "permission": grant.permission,
        "anchorMessageId": grant.anchor_message_id,
        "snapshotThroughMessageId": grant.snapshot_through_message_id,
        "expiresAt": grant.expires_at,
        "revokedAt": grant.revoked_at,
        "createdAt": grant.created_at,
        "lastAccessedAt": grant.last_accessed_at,
    }


def _latest_message(db: Session, conversation_id: str) -> Message | None:
    return db.scalar(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
    )


def _validate_expiration(expires_at: datetime | None) -> datetime | None:
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        raise ApiProblem(
            400,
            "invalid_expiration",
            "만료 시각에는 timezone 정보가 필요합니다.",
        )
    normalized = expires_at.astimezone(UTC)
    if normalized <= utc_now():
        raise ApiProblem(
            400, "invalid_expiration", "만료 시각은 현재보다 이후여야 합니다."
        )
    return normalized


@router.post("", status_code=201)
def create_conversation_share(
    payload: ShareCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    owner = context.user
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == payload.conversation_id,
            Conversation.owner_user_id == owner.id,
            Conversation.organization_id == owner.organization_id,
            Conversation.deleted_at.is_(None),
        )
    )
    if conversation is None:
        raise ApiProblem(404, "not_found", "대화를 찾을 수 없습니다.")

    snapshot_message = _latest_message(db, conversation.id)
    if snapshot_message is None:
        raise ApiProblem(
            409,
            "conversation_has_no_messages",
            "메시지가 있는 대화만 공유할 수 있습니다.",
        )
    anchor_message = snapshot_message
    if payload.anchor_message_id is not None:
        selected_anchor = db.scalar(
            select(Message).where(
                Message.id == payload.anchor_message_id,
                Message.conversation_id == conversation.id,
            )
        )
        if selected_anchor is None:
            raise ApiProblem(
                400, "invalid_anchor", "공유 기준 메시지를 찾을 수 없습니다."
            )
        if (selected_anchor.created_at, selected_anchor.id) > (
            snapshot_message.created_at,
            snapshot_message.id,
        ):
            raise ApiProblem(
                400,
                "invalid_anchor",
                "공유 기준 메시지가 snapshot 범위를 벗어났습니다.",
            )
        anchor_message = selected_anchor

    raw_token = generate_secret_token()
    grant = ConversationShareGrant(
        conversation_id=conversation.id,
        owner_user_id=owner.id,
        recipient_user_id=None,
        scope="conversation_snapshot",
        anchor_message_id=anchor_message.id,
        snapshot_through_message_id=snapshot_message.id,
        permission="view",
        token_hash=hash_token(raw_token),
        expires_at=None,
        created_by_user_id=owner.id,
    )
    db.add(grant)
    db.flush()
    record_audit(
        db,
        action="conversation_share_created",
        target_type="conversation_share",
        target_id=grant.id,
        result="success",
        actor=owner,
        request_id=_request_id(request),
        metadata={
            "conversation_id": conversation.id,
            "access": "anyone_with_link",
            "scope": grant.scope,
            "snapshot_through_message_id": snapshot_message.id,
        },
    )
    db.commit()
    result = _share_payload(grant)
    # The opaque token is returned exactly once. It is never persisted or audited.
    result["urlToken"] = raw_token
    result["viewerPath"] = f"/shared/{raw_token}"
    return result


@router.get("")
def list_conversation_shares(
    conversation_id: str | None = None,
    received: bool = False,
    active_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    principal_filter = (
        ConversationShareGrant.recipient_user_id == user.id
        if received
        else ConversationShareGrant.owner_user_id == user.id
    )
    query = select(ConversationShareGrant).where(principal_filter)
    if conversation_id:
        query = query.where(ConversationShareGrant.conversation_id == conversation_id)
    if active_only:
        query = query.where(
            ConversationShareGrant.revoked_at.is_(None),
            or_(
                ConversationShareGrant.expires_at.is_(None),
                ConversationShareGrant.expires_at > utc_now(),
            ),
        )
    grants = list(
        db.scalars(
            query.order_by(ConversationShareGrant.created_at.desc()).limit(limit)
        )
    )
    recipients: dict[str, User] = {}
    if not received:
        recipient_ids = {grant.recipient_user_id for grant in grants}
        if recipient_ids:
            recipients = {
                recipient.id: recipient
                for recipient in db.scalars(
                    select(User).where(User.id.in_(recipient_ids))
                )
            }
    return {
        "items": [
            _share_payload(grant, recipient=recipients.get(grant.recipient_user_id))
            for grant in grants
        ]
    }


@router.delete("/{share_id}", status_code=204)
def revoke_conversation_share(
    share_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> None:
    actor = context.user
    grant = db.get(ConversationShareGrant, share_id)
    if grant is None:
        raise ApiProblem(404, "not_found", "공유 항목을 찾을 수 없습니다.")
    conversation = db.get(Conversation, grant.conversation_id)
    is_same_organization_admin = (
        actor.role == "admin"
        and conversation is not None
        and conversation.organization_id == actor.organization_id
    )
    if grant.owner_user_id != actor.id and not is_same_organization_admin:
        raise ApiProblem(404, "not_found", "공유 항목을 찾을 수 없습니다.")
    if grant.revoked_at is None:
        grant.revoked_at = utc_now()
        record_audit(
            db,
            action=(
                "admin_share_revoked"
                if actor.id != grant.owner_user_id
                else "conversation_share_revoked"
            ),
            target_type="conversation_share",
            target_id=grant.id,
            result="success",
            actor=actor,
            request_id=_request_id(request),
            metadata={
                "conversation_id": grant.conversation_id,
                "recipient_user_id": grant.recipient_user_id,
            },
        )
        db.commit()


def _resolve_share(
    db: Session,
    *,
    token: str,
    request_id: str | None,
) -> tuple[ConversationShareGrant, Conversation, Message]:
    if not 32 <= len(token) <= 128:
        raise _not_found()
    grant = db.scalar(
        select(ConversationShareGrant).where(
            ConversationShareGrant.token_hash == hash_token(token)
        )
    )
    if grant is None:
        raise _not_found()
    if grant.revoked_at is not None:
        raise _not_found()
    if grant.expires_at is not None and grant.expires_at <= utc_now():
        record_audit(
            db,
            action="conversation_share_expired",
            target_type="conversation_share",
            target_id=grant.id,
            result="denied",
            actor=None,
            request_id=request_id,
            metadata={"conversation_id": grant.conversation_id},
        )
        db.commit()
        raise _not_found()
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == grant.conversation_id,
            Conversation.deleted_at.is_(None),
        )
    )
    marker = db.get(Message, grant.snapshot_through_message_id)
    if (
        conversation is None
        or marker is None
        or marker.conversation_id != grant.conversation_id
    ):
        raise _not_found()
    return grant, conversation, marker


def _snapshot_messages(
    db: Session,
    conversation: Conversation,
    marker: Message,
) -> list[Message]:
    return list(
        db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                or_(
                    Message.created_at < marker.created_at,
                    and_(
                        Message.created_at == marker.created_at,
                        Message.id <= marker.id,
                    ),
                ),
            )
            .order_by(Message.created_at, Message.id)
        )
    )


def _snapshot_attachment_ids(messages: list[Message]) -> set[str]:
    attachment_ids: set[str] = set()
    for message in messages:
        raw_ids = message.metadata_json.get("attachment_ids", [])
        if isinstance(raw_ids, list):
            attachment_ids.update(str(item) for item in raw_ids if item)
        raw_references = message.metadata_json.get("prompt_references", [])
        if not isinstance(raw_references, list):
            continue
        for reference in raw_references:
            if not isinstance(reference, dict) or reference.get("kind") != "file":
                continue
            reference_id = reference.get("reference_id") or reference.get("referenceId")
            if reference_id:
                attachment_ids.add(str(reference_id))
    return attachment_ids


def _snapshot_artifact_versions(
    db: Session,
    grant: ConversationShareGrant,
    allowed_run_ids: set[str],
) -> list[tuple[Artifact, ArtifactVersion]]:
    artifact_query = select(Artifact).where(
        Artifact.conversation_id == grant.conversation_id,
        Artifact.deleted_at.is_(None),
        Artifact.created_at <= grant.created_at,
    )
    if allowed_run_ids:
        artifact_query = artifact_query.where(
            or_(
                Artifact.source_run_id.is_(None),
                Artifact.source_run_id.in_(allowed_run_ids),
            )
        )
    else:
        artifact_query = artifact_query.where(Artifact.source_run_id.is_(None))

    results: list[tuple[Artifact, ArtifactVersion]] = []
    for artifact in db.scalars(
        artifact_query.order_by(Artifact.created_at, Artifact.id)
    ):
        version = db.scalar(
            select(ArtifactVersion)
            .where(
                ArtifactVersion.artifact_id == artifact.id,
                ArtifactVersion.created_at <= grant.created_at,
            )
            .order_by(
                ArtifactVersion.version_number.desc(),
                ArtifactVersion.id.desc(),
            )
            .limit(1)
        )
        if version is not None:
            results.append((artifact, version))
    return results


def _shared_message_payload(
    message: Message,
    *,
    allowed_attachment_ids: set[str],
    allowed_artifact_ids: set[str],
) -> dict[str, object]:
    references: list[dict[str, object]] = []
    raw_references = message.metadata_json.get("prompt_references", [])
    if isinstance(raw_references, list):
        for raw in raw_references:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind", "unknown"))
            reference_id = str(raw.get("reference_id") or raw.get("referenceId") or "")
            allowed = (kind == "file" and reference_id in allowed_attachment_ids) or (
                kind == "artifact" and reference_id in allowed_artifact_ids
            )
            references.append(
                {
                    "kind": kind,
                    "referenceId": reference_id if allowed else None,
                    "displaySnapshot": raw.get("display_snapshot")
                    or raw.get("displaySnapshot")
                    or {},
                    "status": "available" if allowed else "unavailable",
                }
            )
    return {
        "id": message.id,
        "runId": message.run_id,
        "role": message.role,
        "text": message.canonical_text,
        "status": message.status,
        "references": references,
        "createdAt": message.created_at,
        "completedAt": message.updated_at if message.status == "completed" else None,
    }


@router.get("/{token}")
def get_shared_conversation(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    grant, conversation, marker = _resolve_share(
        db,
        token=token,
        request_id=_request_id(request),
    )
    messages = _snapshot_messages(db, conversation, marker)
    message_ids = {message.id for message in messages}
    referenced_attachment_ids = _snapshot_attachment_ids(messages)
    run_ids = {message.run_id for message in messages if message.run_id is not None}
    attachments = (
        list(
            db.scalars(
                select(Attachment)
                .where(
                    Attachment.project_id == conversation.project_id,
                    or_(
                        Attachment.message_id.in_(message_ids),
                        Attachment.id.in_(referenced_attachment_ids),
                    ),
                    Attachment.created_at <= grant.created_at,
                    Attachment.deleted_at.is_(None),
                )
                .order_by(Attachment.created_at, Attachment.id)
            )
        )
        if message_ids or referenced_attachment_ids
        else []
    )
    artifact_versions = _snapshot_artifact_versions(db, grant, run_ids)
    attachment_ids = {attachment.id for attachment in attachments}
    artifact_ids = {artifact.id for artifact, _version in artifact_versions}
    owner = db.get(User, grant.owner_user_id)

    grant.last_accessed_at = utc_now()
    record_audit(
        db,
        action="conversation_share_opened",
        target_type="conversation_share",
        target_id=grant.id,
        result="success",
        actor=None,
        request_id=_request_id(request),
        metadata={
            "conversation_id": conversation.id,
            "snapshot_through_message_id": grant.snapshot_through_message_id,
        },
    )
    db.commit()
    return {
        "share": {
            "id": grant.id,
            "readOnly": True,
            "scope": grant.scope,
            "permission": grant.permission,
            "anchorMessageId": grant.anchor_message_id,
            "snapshotThroughMessageId": grant.snapshot_through_message_id,
            "sharedAt": grant.created_at,
            "expiresAt": grant.expires_at,
        },
        "conversation": {
            "id": conversation.id,
            "title": conversation.title,
            "ownerDisplayName": owner.display_name if owner else None,
        },
        "messages": [
            _shared_message_payload(
                message,
                allowed_attachment_ids=attachment_ids,
                allowed_artifact_ids=artifact_ids,
            )
            for message in messages
        ],
        "attachments": [
            {
                "id": attachment.id,
                "messageId": attachment.message_id,
                "filename": attachment.original_filename,
                "mimeType": attachment.sniffed_mime_type,
                "size": attachment.size_bytes,
                "contentHash": attachment.content_hash,
            }
            for attachment in attachments
        ],
        "artifacts": [
            {
                "id": artifact.id,
                "displayName": artifact.display_name,
                "kind": artifact.kind,
                "mimeType": artifact.mime_type,
                "version": version.version_number,
                "contentHash": version.content_hash,
                "size": version.size_bytes,
                "validationStatus": version.validation_status,
                "createdAt": artifact.created_at,
            }
            for artifact, version in artifact_versions
        ],
    }


def _shared_artifact_version(
    db: Session,
    *,
    grant: ConversationShareGrant,
    conversation: Conversation,
    marker: Message,
    artifact_id: str,
    requested_version: int | None,
) -> tuple[Artifact, ArtifactVersion]:
    messages = _snapshot_messages(db, conversation, marker)
    run_ids = {message.run_id for message in messages if message.run_id is not None}
    for artifact, snapshot_version in _snapshot_artifact_versions(db, grant, run_ids):
        if artifact.id != artifact_id:
            continue
        if requested_version is None or snapshot_version.version_number == requested_version:
            return artifact, snapshot_version
        version = db.scalar(
            select(ArtifactVersion).where(
                ArtifactVersion.artifact_id == artifact.id,
                ArtifactVersion.version_number == requested_version,
                ArtifactVersion.created_at <= grant.created_at,
            )
        )
        if version is not None:
            return artifact, version
        break
    raise _not_found()


@router.get("/{token}/artifacts/{artifact_id}/download")
def download_shared_artifact(
    token: str,
    artifact_id: str,
    request: Request,
    version: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    grant, conversation, marker = _resolve_share(
        db,
        token=token,
        request_id=_request_id(request),
    )
    artifact, stored_version = _shared_artifact_version(
        db,
        grant=grant,
        conversation=conversation,
        marker=marker,
        artifact_id=artifact_id,
        requested_version=version,
    )
    if settings.artifacts_dir is None:
        raise ApiProblem(
            503, "storage_unavailable", "Artifact 저장소를 사용할 수 없습니다."
        )
    try:
        content = ManagedLocalStorage(settings.artifacts_dir).read_bytes(
            stored_version.storage_key,
            expected_sha256=stored_version.content_hash,
        )
    except StorageNotFoundError as exc:
        raise ApiProblem(
            503, "artifact_content_missing", "Artifact 원본을 읽을 수 없습니다."
        ) from exc
    grant.last_accessed_at = utc_now()
    record_audit(
        db,
        action="conversation_share_opened",
        target_type="conversation_share",
        target_id=grant.id,
        result="success",
        actor=None,
        request_id=_request_id(request),
        metadata={"artifact_id": artifact.id, "version": stored_version.version_number},
    )
    db.commit()
    encoded = quote(artifact.display_name, safe="")
    return StreamingResponse(
        iter([content]),
        media_type=artifact.mime_type,
        headers={
            "Content-Length": str(len(content)),
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
            "ETag": f'"{stored_version.content_hash}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/{token}/attachments/{attachment_id}/download")
def download_shared_attachment(
    token: str,
    attachment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    grant, conversation, marker = _resolve_share(
        db,
        token=token,
        request_id=_request_id(request),
    )
    messages = _snapshot_messages(db, conversation, marker)
    message_ids = {message.id for message in messages}
    referenced_attachment_ids = _snapshot_attachment_ids(messages)
    attachment = (
        db.scalar(
            select(Attachment).where(
                Attachment.id == attachment_id,
                Attachment.project_id == conversation.project_id,
                or_(
                    Attachment.message_id.in_(message_ids),
                    Attachment.id.in_(referenced_attachment_ids),
                ),
                Attachment.created_at <= grant.created_at,
                Attachment.deleted_at.is_(None),
            )
        )
        if message_ids or referenced_attachment_ids
        else None
    )
    if attachment is None:
        raise _not_found()
    if settings.files_dir is None:
        raise ApiProblem(
            503, "storage_unavailable", "첨부 저장소를 사용할 수 없습니다."
        )
    try:
        content = ManagedLocalStorage(settings.files_dir).read_bytes(
            attachment.storage_key,
            expected_sha256=attachment.content_hash,
        )
    except StorageNotFoundError as exc:
        raise ApiProblem(
            503, "attachment_content_missing", "첨부 원본을 읽을 수 없습니다."
        ) from exc
    grant.last_accessed_at = utc_now()
    record_audit(
        db,
        action="conversation_share_opened",
        target_type="conversation_share",
        target_id=grant.id,
        result="success",
        actor=None,
        request_id=_request_id(request),
        metadata={"attachment_id": attachment.id},
    )
    db.commit()
    encoded = quote(attachment.original_filename, safe="")
    return StreamingResponse(
        iter([content]),
        media_type=attachment.sniffed_mime_type,
        headers={
            "Content-Length": str(len(content)),
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
            "ETag": f'"{attachment.content_hash}"',
            "Cache-Control": "private, no-store",
        },
    )
