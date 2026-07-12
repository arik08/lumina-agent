from __future__ import annotations

import hashlib
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...artifacts.service import (
    artifact_summary,
    create_artifact_version,
    current_artifact_version,
    delete_user_draft_if_matches,
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
from ...models import Artifact, ArtifactVersion, Project, User
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


def _storage(settings: Settings) -> ManagedLocalStorage:
    if settings.artifacts_dir is None:
        raise RuntimeError("LUMINA_ARTIFACTS_DIR is not configured")
    return ManagedLocalStorage(settings.artifacts_dir)


def _version_payload(version: ArtifactVersion, content: bytes) -> dict[str, object]:
    mime_type = _mime_from_key(version.storage_key)
    source_text = None
    if version.storage_key.endswith((".html", ".md", ".txt", ".json", ".csv")):
        source_text = content.decode("utf-8", errors="replace")
    return {
        "artifactId": version.artifact_id,
        "version": version.version_number,
        "mimeType": mime_type,
        "sourceText": source_text,
        "previewUrl": (
            f"/api/artifacts/{version.artifact_id}/preview?version={version.version_number}"
            if mime_type.startswith("image/") or mime_type == "application/pdf"
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    _artifact, version, content = read_artifact_version(
        db,
        _storage(settings),
        user=user,
        artifact_id=artifact_id,
        version_number=version_number,
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
    if (
        artifact.current_version_number != payload.base_version
        and current.content_hash == digest
    ):
        stored_content = _storage(settings).read_bytes(
            current.storage_key, expected_sha256=current.content_hash
        )
        if delete_user_draft_if_matches(
            db,
            user=context.user,
            artifact_id=artifact.id,
            base_version=payload.base_version,
            etag=expected_draft_etag,
            content_hash=digest,
        ):
            db.commit()
        return _version_payload(current, stored_content)
    version = create_artifact_version(
        db,
        _storage(settings),
        user=context.user,
        artifact_id=artifact.id,
        base_version=payload.base_version,
        content=content,
        change_type=payload.change_type,
        change_summary=payload.change_summary,
    )
    delete_user_draft_if_matches(
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
    stored_content = _storage(settings).read_bytes(
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
    _artifact, source, content = read_artifact_version(
        db,
        _storage(settings),
        user=context.user,
        artifact_id=artifact.id,
        version_number=payload.source_version,
    )
    version = create_artifact_version(
        db,
        _storage(settings),
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
    stored_content = _storage(settings).read_bytes(
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
    draft = save_draft(
        db,
        _storage(settings),
        user=context.user,
        artifact_id=artifact_id,
        base_version=payload.base_version,
        content=payload.content.encode("utf-8"),
        expected_etag=_etag_value(if_match),
    )
    db.commit()
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
        or artifact.mime_type == "application/pdf"
    ):
        raise ApiProblem(
            415,
            "artifact_preview_unsupported",
            "이미지와 PDF Artifact만 바이너리 미리보기를 지원합니다.",
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
