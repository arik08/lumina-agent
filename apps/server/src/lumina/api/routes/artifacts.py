from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from contextlib import suppress
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...artifacts.service import (
    artifact_summary,
    create_artifact,
    create_artifact_version,
    current_artifact_version,
    delete_user_draft_if_matches,
    discard_artifact_storage,
    ensure_artifact_text_editable,
    read_user_draft,
    read_artifact_version,
    require_artifact,
    save_draft,
)
from ...audit import record_audit
from ...authorization import project_access_query
from ...config import Settings, get_settings
from ...db import get_db
from ...messages.service import require_message
from ...models import Artifact, ArtifactVersion, Conversation, Project, User
from ...storage import ManagedLocalStorage
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem
from ..schemas import (
    ArtifactDraftResponse,
    ArtifactDraftSave,
    ArtifactRestoreRequest,
    ArtifactVersionCreate,
)


router = APIRouter(prefix="/artifacts", tags=["artifacts"])

_INTERNAL_ARTIFACT_METADATA_LINE = re.compile(
    r"^[ \t]*(?:[-*+]\s*)?(?:\*\*|__)?Artifact(?: ID)?"
    r"(?:(?:\*\*|__)?[ \t]*:|[ \t]*:(?:\*\*|__))"
    r"[ \t]*`?[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}`?[ \t]*\r?\n?",
    flags=re.IGNORECASE | re.MULTILINE,
)
_REPORT_OPEN_LINE = re.compile(r"^[ \t]*보고서 열기[ \t]*\r?\n?", re.MULTILINE)
_UNSAFE_FILE_NAME_CHARACTER = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_HTML_PREVIEW_BRIDGE = b'<script src="/artifact-preview-bridge.js"></script>'
_HTML_PREVIEW_CHUNK_SIZE = 16 * 1024
_HTML_CLOSING_BODY = re.compile(br"</body\b", flags=re.IGNORECASE)
_TEXT_ARTIFACT_SUFFIXES = (".html", ".md", ".txt", ".json", ".csv")


def _storage(settings: Settings) -> ManagedLocalStorage:
    if settings.artifacts_dir is None:
        raise RuntimeError("LUMINA_ARTIFACTS_DIR is not configured")
    return ManagedLocalStorage(settings.artifacts_dir)


def _message_markdown(text: str, *, has_artifacts: bool) -> str:
    content = _INTERNAL_ARTIFACT_METADATA_LINE.sub("", text)
    if has_artifacts:
        content = _REPORT_OPEN_LINE.sub("", content)
    return content


def _message_markdown_name(conversation: Conversation, created_at: datetime) -> str:
    title = _UNSAFE_FILE_NAME_CHARACTER.sub(" ", conversation.title)
    title = " ".join(title.split()).strip(" .")
    if not title or title in {"제목 없음", "새 작업"}:
        title = "답변"
    return f"{title[:80].rstrip()}_{created_at:%Y%m%d_%H%M%S}.md"


def _version_payload(
    version: ArtifactVersion, content: bytes | None
) -> dict[str, object]:
    mime_type = _mime_from_key(version.storage_key)
    source_available = version.storage_key.endswith(_TEXT_ARTIFACT_SUFFIXES)
    source_text = None
    if source_available and content is not None:
        source_text = content.decode("utf-8", errors="replace")
    return {
        "artifactId": version.artifact_id,
        "version": version.version_number,
        "mimeType": mime_type,
        "sourceText": source_text,
        "sourceAvailable": source_available,
        "previewUrl": (
            f"/api/artifacts/{version.artifact_id}/preview?version={version.version_number}"
            if mime_type.startswith("image/")
            or mime_type in {"application/pdf", "text/html"}
            else None
        ),
        "contentHash": version.content_hash,
        "size": version.size_bytes,
        "validationStatus": version.validation_status,
        "validation": version.validation_json,
        "metadata": version.renderer_manifest_json.get("generation"),
        "changeType": version.change_type,
        "parentVersionId": version.parent_version_id,
        "sourceVersionId": version.source_version_id,
        "etag": version.content_hash,
        "createdAt": version.created_at,
    }


@router.get("")
def list_artifacts(
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    project_ids = project_access_query(user).with_only_columns(Project.id)
    query = select(Artifact).where(
        Artifact.project_id.in_(project_ids), Artifact.deleted_at.is_(None)
    )
    if project_id:
        query = query.where(Artifact.project_id == project_id)
    artifacts = list(
        db.scalars(query.order_by(Artifact.updated_at.desc(), Artifact.id).limit(limit))
    )
    return {
        "items": [
            artifact_summary(artifact, current_artifact_version(db, artifact))
            for artifact in artifacts
        ],
        "nextCursor": None,
        "hasMore": False,
    }


@router.post("/from-message/{message_id}", status_code=201)
def create_markdown_artifact_from_message(
    message_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    message = require_message(db, context.user, message_id, assistant_only=True)
    conversation = db.get(Conversation, message.conversation_id)
    if conversation is None:
        raise ApiProblem(404, "not_found", "대화를 찾을 수 없습니다.")
    has_artifacts = bool(
        message.run_id
        and db.scalar(
            select(Artifact.id)
            .where(
                Artifact.source_run_id == message.run_id,
                Artifact.deleted_at.is_(None),
            )
            .limit(1)
        )
    )
    content = _message_markdown(
        message.canonical_text, has_artifacts=has_artifacts
    )
    if not content.strip():
        raise ApiProblem(
            409,
            "assistant_message_empty",
            "Markdown으로 저장할 답변 내용이 없습니다.",
        )
    storage = _storage(settings)
    artifact, version = create_artifact(
        db,
        storage,
        user=context.user,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        source_run_id=message.run_id,
        display_name=_message_markdown_name(conversation, message.created_at),
        kind="markdown",
        mime_type="text/markdown",
        content=content.encode("utf-8"),
        change_type="saved_from_message",
        change_summary="채팅 답변을 Markdown Artifact로 저장",
        renderer_manifest={
            "source": {"type": "assistant_message", "messageId": message.id}
        },
    )
    try:
        record_audit(
            db,
            action="message_markdown_artifact_created",
            target_type="artifact",
            target_id=artifact.id,
            result="success",
            actor=context.user,
            request_id=getattr(request.state, "request_id", None),
            metadata={"message_id": message.id, "version": version.version_number},
        )
        db.commit()
    except BaseException:
        with suppress(Exception):
            db.rollback()
        discard_artifact_storage(storage, version.storage_key)
        raise
    return artifact_summary(artifact, version)


@router.get("/{artifact_id}")
def get_artifact(
    artifact_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    artifact = require_artifact(db, user, artifact_id)
    current = current_artifact_version(db, artifact)
    payload = artifact_summary(artifact, current)
    payload["versions"] = list(
        db.scalars(
            select(ArtifactVersion.version_number)
            .where(ArtifactVersion.artifact_id == artifact.id)
            .order_by(ArtifactVersion.version_number.desc())
        )
    )
    return payload


@router.get("/{artifact_id}/versions/{version_number}")
def get_version(
    artifact_id: str,
    version_number: int,
    include_source: bool = Query(default=True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    artifact = require_artifact(db, user, artifact_id)
    version = db.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact.id,
            ArtifactVersion.version_number == version_number,
        )
    )
    if version is None:
        raise ApiProblem(404, "version_not_found", "Artifact 버전을 찾을 수 없습니다.")
    content = None
    if include_source and version.storage_key.endswith(_TEXT_ARTIFACT_SUFFIXES):
        content = _storage(settings).read_bytes(
            version.storage_key, expected_sha256=version.content_hash
        )
    return _version_payload(version, content)


@router.post("/{artifact_id}/versions", status_code=201)
def post_version(
    artifact_id: str,
    payload: ArtifactVersionCreate,
    request: Request,
    if_match: str | None = Header(default=None, alias="If-Match"),
    draft_if_match: str | None = Header(
        default=None, alias="X-Artifact-Draft-If-Match"
    ),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    if not idempotency_key or len(idempotency_key) < 8:
        raise ApiProblem(
            400, "idempotency_key_required", "Idempotency-Key가 필요합니다."
        )
    artifact = require_artifact(db, context.user, artifact_id, write=True)
    ensure_artifact_text_editable(artifact)
    current = current_artifact_version(db, artifact)
    if current is None:
        raise ApiProblem(
            409, "artifact_has_no_version", "Artifact 기준 버전이 없습니다."
        )
    expected = (if_match or "").strip().strip('"')
    if not expected or expected != current.content_hash:
        raise ApiProblem(
            409, "artifact_etag_conflict", "Artifact가 다른 곳에서 변경되었습니다."
        )
    content = payload.source_text.encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    expected_draft_etag = _etag_value(draft_if_match)
    storage = _storage(settings)
    if (
        artifact.current_version_number != payload.base_version
        and current.content_hash == digest
    ):
        stored_content = storage.read_bytes(
            current.storage_key, expected_sha256=current.content_hash
        )
        duplicate_draft_key = delete_user_draft_if_matches(
            db,
            user=context.user,
            artifact_id=artifact.id,
            base_version=payload.base_version,
            etag=expected_draft_etag,
            content_hash=digest,
        )
        if duplicate_draft_key is not None:
            db.commit()
            discard_artifact_storage(storage, duplicate_draft_key)
        return _version_payload(current, stored_content)
    version = create_artifact_version(
        db,
        storage,
        user=context.user,
        artifact_id=artifact.id,
        base_version=payload.base_version,
        content=content,
        change_type=payload.change_type,
        change_summary=payload.change_summary,
    )
    removed_draft_key: str | None = None
    try:
        removed_draft_key = delete_user_draft_if_matches(
            db,
            user=context.user,
            artifact_id=artifact.id,
            base_version=payload.base_version,
            etag=expected_draft_etag,
            content_hash=digest,
        )
        record_audit(
            db,
            action="artifact_edited",
            target_type="artifact",
            target_id=artifact.id,
            result="success",
            actor=context.user,
            request_id=getattr(request.state, "request_id", None),
            metadata={
                "version": version.version_number,
                "idempotency_key": idempotency_key,
            },
        )
        db.commit()
    except BaseException:
        with suppress(Exception):
            db.rollback()
        discard_artifact_storage(storage, version.storage_key)
        raise
    if removed_draft_key is not None:
        discard_artifact_storage(storage, removed_draft_key)
    stored_content = storage.read_bytes(
        version.storage_key, expected_sha256=version.content_hash
    )
    return _version_payload(version, stored_content)


@router.post("/{artifact_id}/restore", status_code=201)
def restore_version(
    artifact_id: str,
    payload: ArtifactRestoreRequest,
    request: Request,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    if not idempotency_key or len(idempotency_key) < 8:
        raise ApiProblem(
            400, "idempotency_key_required", "Idempotency-Key가 필요합니다."
        )
    artifact = require_artifact(db, context.user, artifact_id, write=True)
    ensure_artifact_text_editable(artifact)
    current = current_artifact_version(db, artifact)
    if current is None:
        raise ApiProblem(
            409, "artifact_has_no_version", "Artifact 기준 버전이 없습니다."
        )
    expected = (if_match or "").strip().strip('"')
    if not expected or expected != current.content_hash:
        raise ApiProblem(
            409, "artifact_etag_conflict", "Artifact가 다른 곳에서 변경되었습니다."
        )
    storage = _storage(settings)
    _artifact, source, content = read_artifact_version(
        db,
        storage,
        user=context.user,
        artifact_id=artifact.id,
        version_number=payload.source_version,
    )
    version = create_artifact_version(
        db,
        storage,
        user=context.user,
        artifact_id=artifact.id,
        base_version=current.version_number,
        content=content,
        change_type="restore",
        change_summary=(
            payload.change_summary.strip() or f"v{source.version_number} 버전에서 복원"
        ),
        source_version=source,
    )
    try:
        record_audit(
            db,
            action="artifact_version_restored",
            target_type="artifact",
            target_id=artifact.id,
            result="success",
            actor=context.user,
            request_id=getattr(request.state, "request_id", None),
            metadata={
                "version": version.version_number,
                "source_version": source.version_number,
                "idempotency_key": idempotency_key,
            },
        )
        db.commit()
    except BaseException:
        with suppress(Exception):
            db.rollback()
        discard_artifact_storage(storage, version.storage_key)
        raise
    stored_content = storage.read_bytes(
        version.storage_key, expected_sha256=version.content_hash
    )
    return _version_payload(version, stored_content)


@router.get("/{artifact_id}/draft", response_model=ArtifactDraftResponse)
def get_draft(
    artifact_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ArtifactDraftResponse:
    artifact, draft, content = read_user_draft(
        db,
        _storage(settings),
        user=user,
        artifact_id=artifact_id,
    )
    return _draft_payload(
        artifact.current_version_number,
        draft.artifact_id,
        draft.base_version_number,
        content,
        draft.etag,
        draft.updated_at,
    )


@router.put("/{artifact_id}/draft", response_model=ArtifactDraftResponse)
def put_draft(
    artifact_id: str,
    payload: ArtifactDraftSave,
    if_match: str | None = Header(default=None, alias="If-Match"),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ArtifactDraftResponse:
    artifact = require_artifact(db, context.user, artifact_id, write=True)
    ensure_artifact_text_editable(artifact)
    storage = _storage(settings)
    draft, previous_storage_key = save_draft(
        db,
        storage,
        user=context.user,
        artifact_id=artifact_id,
        base_version=payload.base_version,
        content=payload.content.encode("utf-8"),
        expected_etag=_etag_value(if_match),
    )
    try:
        db.commit()
    except BaseException:
        with suppress(Exception):
            db.rollback()
        discard_artifact_storage(storage, draft.storage_key)
        raise
    if previous_storage_key is not None:
        discard_artifact_storage(storage, previous_storage_key)
    return _draft_payload(
        artifact.current_version_number,
        draft.artifact_id,
        draft.base_version_number,
        payload.content.encode("utf-8"),
        draft.etag,
        draft.updated_at,
    )


@router.get("/{artifact_id}/download")
def download_artifact(
    artifact_id: str,
    version: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    artifact = require_artifact(db, user, artifact_id)
    selected_version = version or artifact.current_version_number
    if selected_version is None:
        raise ApiProblem(404, "version_not_found", "다운로드할 버전이 없습니다.")
    _artifact, stored_version, content = read_artifact_version(
        db,
        _storage(settings),
        user=user,
        artifact_id=artifact.id,
        version_number=selected_version,
    )
    filename = artifact.display_name
    encoded = quote(filename, safe="")
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


@router.get("/{artifact_id}/preview")
def preview_artifact(
    artifact_id: str,
    version: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    artifact = require_artifact(db, user, artifact_id)
    if not (
        artifact.mime_type.startswith("image/")
        or artifact.mime_type in {"application/pdf", "text/html"}
    ):
        raise ApiProblem(
            415,
            "artifact_preview_unsupported",
            "HTML, 이미지와 PDF Artifact만 미리보기를 지원합니다.",
        )
    selected_version = version or artifact.current_version_number
    if selected_version is None:
        raise ApiProblem(404, "version_not_found", "미리 볼 버전이 없습니다.")
    _artifact, stored_version, content = read_artifact_version(
        db,
        _storage(settings),
        user=user,
        artifact_id=artifact.id,
        version_number=selected_version,
    )
    if artifact.mime_type == "text/html":
        return StreamingResponse(
            _stream_html_preview(content),
            media_type="text/html",
            headers={
                "Content-Disposition": "inline",
                "ETag": f'W/"{stored_version.content_hash}-preview-v1"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    return Response(
        content=content,
        media_type=artifact.mime_type,
        headers={
            "Content-Disposition": "inline",
            "ETag": f'"{stored_version.content_hash}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _stream_html_preview(content: bytes) -> Iterator[bytes]:
    closing_body = -1
    for match in _HTML_CLOSING_BODY.finditer(content):
        closing_body = match.start()
    insertion = closing_body if closing_body >= 0 else len(content)
    for offset in range(0, insertion, _HTML_PREVIEW_CHUNK_SIZE):
        yield content[offset : min(insertion, offset + _HTML_PREVIEW_CHUNK_SIZE)]
    yield _HTML_PREVIEW_BRIDGE
    for offset in range(insertion, len(content), _HTML_PREVIEW_CHUNK_SIZE):
        yield content[offset : offset + _HTML_PREVIEW_CHUNK_SIZE]


def _mime_from_key(key: str) -> str:
    if key.endswith(".html"):
        return "text/html"
    if key.endswith(".md"):
        return "text/markdown"
    if key.endswith(".txt"):
        return "text/plain"
    if key.endswith(".csv"):
        return "text/csv"
    if key.endswith(".json"):
        return "application/json"
    if key.endswith(".png"):
        return "image/png"
    if key.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if key.endswith(".webp"):
        return "image/webp"
    if key.endswith(".pdf"):
        return "application/pdf"
    if key.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if key.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if key.endswith(".pptx"):
        return (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
    return "application/octet-stream"


def _etag_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) >= 2 and normalized.startswith('"') and normalized.endswith('"'):
        normalized = normalized[1:-1]
    return normalized or None


def _draft_payload(
    current_version: int | None,
    artifact_id: str,
    base_version: int,
    content: bytes,
    etag: str,
    updated_at: datetime,
) -> ArtifactDraftResponse:
    return ArtifactDraftResponse(
        artifact_id=artifact_id,
        base_version=base_version,
        content=content.decode("utf-8", errors="replace"),
        etag=etag,
        updated_at=updated_at,
        stale=current_version != base_version,
    )
