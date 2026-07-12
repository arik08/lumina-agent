from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...config import Settings, get_settings
from ...db import get_db
from ...models import ProjectFile, ProjectFileVersion, User
from ...project_files import (
    create_project_file,
    create_project_file_version,
    get_project_file,
    get_project_file_version,
    list_project_files,
    move_project_file,
    normalize_logical_path,
    soft_delete_project_file,
)
from ...storage import ManagedLocalStorage
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..schemas import (
    ProjectFileDetailResponse,
    ProjectFileMove,
    ProjectFileResponse,
)


router = APIRouter(prefix="/projects/{project_id}/files", tags=["project-files"])


def _storage(settings: Settings) -> ManagedLocalStorage:
    if settings.files_dir is None:
        raise RuntimeError("LUMINA_FILES_DIR is not configured")
    return ManagedLocalStorage(settings.files_dir)


def _version_payload(version: ProjectFileVersion) -> dict[str, object]:
    return {
        "id": version.id,
        "version": version.version_number,
        "contentHash": version.content_hash,
        "mimeType": version.mime_type,
        "size": version.size_bytes,
        "originalFilename": version.original_filename,
        "extractionStatus": version.extraction_status,
        "extractionVersion": version.extraction_version,
        "locatorMap": version.locator_map_json,
        "sourceRunId": version.source_run_id,
        "changeReason": version.change_reason,
        "createdByUserId": version.created_by_user_id,
        "createdAt": version.created_at,
    }


def _file_payload(
    project_file: ProjectFile, version: ProjectFileVersion
) -> dict[str, object]:
    return {
        "id": project_file.id,
        "projectId": project_file.project_id,
        "logicalPath": project_file.logical_path,
        "displayName": PurePosixPath(project_file.logical_path).name,
        "status": project_file.status,
        "revision": project_file.revision,
        "currentVersion": project_file.current_version_number,
        "contentHash": version.content_hash,
        "mimeType": version.mime_type,
        "size": version.size_bytes,
        "extractionStatus": version.extraction_status,
        "createdByUserId": project_file.created_by_user_id,
        "createdAt": project_file.created_at,
        "updatedAt": project_file.updated_at,
    }


def _latest_version_map(
    db: Session, rows: list[ProjectFile]
) -> dict[str, ProjectFileVersion]:
    if not rows:
        return {}
    file_ids = [row.id for row in rows]
    versions = db.scalars(
        select(ProjectFileVersion)
        .join(ProjectFile, ProjectFile.id == ProjectFileVersion.project_file_id)
        .where(
            ProjectFileVersion.project_file_id.in_(file_ids),
            ProjectFileVersion.version_number == ProjectFile.current_version_number,
        )
    )
    return {version.project_file_id: version for version in versions}


@router.get("", response_model=list[ProjectFileResponse])
def get_project_files(
    project_id: str,
    q: str = Query(default="", max_length=500),
    include_deleted: bool = Query(default=False, alias="includeDeleted"),
    limit: int = Query(default=200, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    rows = list_project_files(
        db,
        user,
        project_id,
        query=q,
        include_deleted=include_deleted,
        limit=limit,
    )
    versions = _latest_version_map(db, rows)
    return [_file_payload(row, versions[row.id]) for row in rows if row.id in versions]


@router.post("", status_code=201, response_model=ProjectFileResponse)
async def post_project_file(
    project_id: str,
    request: Request,
    file: UploadFile = File(),
    logical_path: str | None = Form(default=None, alias="logicalPath", max_length=1000),
    change_reason: str = Form(default="", alias="changeReason", max_length=500),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    content = await file.read(settings.max_upload_bytes + 1)
    original_filename = _safe_original_filename(file.filename)
    target_path = normalize_logical_path(logical_path or original_filename)
    project_file, version = create_project_file(
        db,
        user=context.user,
        project_id=project_id,
        logical_path=target_path,
        original_filename=original_filename,
        content=content,
        change_reason=change_reason,
        max_upload_bytes=settings.max_upload_bytes,
        storage=_storage(settings),
    )
    record_audit(
        db,
        action="project_file_created",
        target_type="project_file",
        target_id=project_file.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={
            "project_id": project_id,
            "logical_path": project_file.logical_path,
            "version": version.version_number,
            "content_hash": version.content_hash,
        },
    )
    db.commit()
    return _file_payload(project_file, version)


@router.get("/{file_id}", response_model=ProjectFileDetailResponse)
def get_project_file_detail(
    project_id: str,
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    project_file = get_project_file(db, user, project_id, file_id)
    latest = get_project_file_version(db, project_file)
    versions = list(
        db.scalars(
            select(ProjectFileVersion)
            .where(ProjectFileVersion.project_file_id == project_file.id)
            .order_by(ProjectFileVersion.version_number.desc())
        )
    )
    return {
        **_file_payload(project_file, latest),
        "versions": [_version_payload(item) for item in versions],
    }


@router.patch("/{file_id}", response_model=ProjectFileResponse)
def patch_project_file(
    project_id: str,
    file_id: str,
    payload: ProjectFileMove,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    project_file = move_project_file(
        db,
        user=context.user,
        project_id=project_id,
        file_id=file_id,
        logical_path=payload.logical_path,
        expected_revision=payload.expected_revision,
    )
    latest = get_project_file_version(db, project_file)
    record_audit(
        db,
        action="project_file_moved",
        target_type="project_file",
        target_id=project_file.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"project_id": project_id, "logical_path": project_file.logical_path},
    )
    db.commit()
    return _file_payload(project_file, latest)


@router.post("/{file_id}/versions", status_code=201, response_model=ProjectFileResponse)
async def post_project_file_version(
    project_id: str,
    file_id: str,
    request: Request,
    file: UploadFile = File(),
    base_version: int = Form(alias="baseVersion", ge=1),
    change_reason: str = Form(default="", alias="changeReason", max_length=500),
    source_run_id: str | None = Form(default=None, alias="sourceRunId", max_length=36),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    content = await file.read(settings.max_upload_bytes + 1)
    project_file, version = create_project_file_version(
        db,
        user=context.user,
        project_id=project_id,
        file_id=file_id,
        base_version=base_version,
        original_filename=_safe_original_filename(file.filename),
        content=content,
        change_reason=change_reason,
        source_run_id=source_run_id,
        max_upload_bytes=settings.max_upload_bytes,
        storage=_storage(settings),
    )
    record_audit(
        db,
        action="project_file_version_created",
        target_type="project_file",
        target_id=project_file.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={
            "project_id": project_id,
            "version": version.version_number,
            "content_hash": version.content_hash,
            "source_run_id": source_run_id,
        },
    )
    db.commit()
    return _file_payload(project_file, version)


@router.get("/{file_id}/download")
def download_project_file(
    project_id: str,
    file_id: str,
    version: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    project_file = get_project_file(db, user, project_id, file_id)
    selected = get_project_file_version(db, project_file, version)
    content = _storage(settings).read_bytes(
        selected.storage_key, expected_sha256=selected.content_hash
    )
    filename = PurePosixPath(project_file.logical_path).name
    return Response(
        content=content,
        media_type=selected.mime_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename=project-file; filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.delete("/{file_id}", status_code=204)
def delete_project_file(
    project_id: str,
    file_id: str,
    request: Request,
    expected_revision: int = Query(alias="expectedRevision", ge=1),
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    project_file = soft_delete_project_file(
        db,
        user=context.user,
        project_id=project_id,
        file_id=file_id,
        expected_revision=expected_revision,
    )
    record_audit(
        db,
        action="project_file_deleted",
        target_type="project_file",
        target_id=project_file.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"project_id": project_id, "logical_path": project_file.logical_path},
    )
    db.commit()
    return Response(status_code=204)


def _safe_original_filename(value: str | None) -> str:
    filename = (value or "file").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename or len(filename) > 500:
        return "file"
    return filename
