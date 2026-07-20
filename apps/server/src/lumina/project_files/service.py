from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..attachments import MIME_BY_EXTENSION, extract_attachment_text, sniff_mime
from ..authorization import require_conversation, require_project
from ..models import (
    ProjectFile,
    ProjectFileVersion,
    ProjectFolder,
    Run,
    User,
    new_uuid,
    utc_now,
)
from ..storage import ManagedStorage, StorageError, StoredObject


MAX_LOGICAL_PATH_LENGTH = 1000
MAX_PATH_SEGMENT_LENGTH = 255
EXTRACTION_VERSION = "lumina-text-v1"


@dataclass(frozen=True, slots=True)
class PreparedProjectFile:
    content: bytes
    content_hash: str
    extension: str
    mime_type: str
    extraction_status: str
    extraction_text: str
    locator_map: dict[str, Any]
    extraction_metadata: dict[str, Any]


def normalize_logical_path(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    if not normalized or normalized != normalized.strip():
        raise ApiProblem(
            422,
            "invalid_project_file_path",
            "파일 경로의 앞뒤에는 공백을 사용할 수 없습니다.",
        )
    if len(normalized) > MAX_LOGICAL_PATH_LENGTH:
        raise ApiProblem(
            422,
            "invalid_project_file_path",
            "파일 경로가 허용 길이를 초과했습니다.",
        )
    if normalized.startswith("/") or "\\" in normalized or "\x00" in normalized:
        raise ApiProblem(
            422,
            "invalid_project_file_path",
            "Project 파일 경로는 상대 POSIX 경로여야 합니다.",
        )
    if any(ord(character) < 32 for character in normalized):
        raise ApiProblem(
            422,
            "invalid_project_file_path",
            "파일 경로에 제어 문자를 사용할 수 없습니다.",
        )
    segments = normalized.split("/")
    if any(
        not segment
        or segment in {".", ".."}
        or segment != segment.strip()
        or len(segment) > MAX_PATH_SEGMENT_LENGTH
        or ":" in segment
        for segment in segments
    ):
        raise ApiProblem(
            422,
            "invalid_project_file_path",
            "파일 경로에 비어 있거나 안전하지 않은 구간이 있습니다.",
        )
    canonical = PurePosixPath(*segments).as_posix()
    if canonical != normalized:
        raise ApiProblem(
            422,
            "invalid_project_file_path",
            "파일 경로를 정규화한 뒤 다시 시도해 주세요.",
        )
    return canonical


def logical_path_key(logical_path: str) -> str:
    return unicodedata.normalize("NFC", logical_path).casefold()


def list_project_files(
    db: Session,
    user: User,
    project_id: str,
    *,
    query: str = "",
    include_deleted: bool = False,
    limit: int = 200,
    cursor: tuple[datetime, str, str] | None = None,
) -> list[ProjectFile]:
    require_project(db, user, project_id)
    statement = select(ProjectFile).where(ProjectFile.project_id == project_id)
    if not include_deleted:
        statement = statement.where(ProjectFile.deleted_at.is_(None))
    tokens = tuple(token for token in query.casefold().split() if token)
    if tokens:
        normalized_path = func.lower(ProjectFile.logical_path)
        statement = statement.where(
            and_(
                *(
                    normalized_path.contains(token, autoescape=True)
                    for token in tokens[:12]
                )
            )
        )
    if cursor is not None:
        updated_at, logical_path, file_id = cursor
        statement = statement.where(
            or_(
                ProjectFile.updated_at < updated_at,
                and_(
                    ProjectFile.updated_at == updated_at,
                    ProjectFile.logical_path > logical_path,
                ),
                and_(
                    ProjectFile.updated_at == updated_at,
                    ProjectFile.logical_path == logical_path,
                    ProjectFile.id > file_id,
                ),
            )
        )
    return list(
        db.scalars(
            statement.order_by(
                ProjectFile.updated_at.desc(),
                ProjectFile.logical_path,
                ProjectFile.id,
            ).limit(limit)
        )
    )


def get_project_file(
    db: Session,
    user: User,
    project_id: str,
    file_id: str,
    *,
    write: bool = False,
    include_deleted: bool = False,
) -> ProjectFile:
    require_project(db, user, project_id, write=write)
    project_file = db.get(ProjectFile, file_id)
    if (
        project_file is None
        or project_file.project_id != project_id
        or (project_file.deleted_at is not None and not include_deleted)
    ):
        raise ApiProblem(
            404, "project_file_not_found", "Project 파일을 찾을 수 없습니다."
        )
    return project_file


def get_project_file_version(
    db: Session,
    project_file: ProjectFile,
    selector: int | str | None = None,
) -> ProjectFileVersion:
    version: ProjectFileVersion | None = None
    if selector is None:
        selector = project_file.current_version_number
    if isinstance(selector, int) or str(selector).removeprefix("v").isdigit():
        version_number = int(str(selector).removeprefix("v"))
        version = db.scalar(
            select(ProjectFileVersion).where(
                ProjectFileVersion.project_file_id == project_file.id,
                ProjectFileVersion.version_number == version_number,
            )
        )
    else:
        version = db.scalar(
            select(ProjectFileVersion)
            .where(
                ProjectFileVersion.project_file_id == project_file.id,
                ProjectFileVersion.content_hash == str(selector),
            )
            .order_by(ProjectFileVersion.version_number.desc())
            .limit(1)
        )
    if version is None:
        raise ApiProblem(
            409,
            "reference_version_unavailable",
            "Project 파일의 지정 버전을 사용할 수 없습니다.",
        )
    return version


def prepare_project_file(
    *, logical_path: str, content: bytes, max_upload_bytes: int
) -> PreparedProjectFile:
    if len(content) > max_upload_bytes:
        raise ApiProblem(
            413,
            "project_file_too_large",
            "Project 파일이 허용 크기를 초과했습니다.",
        )
    extension = PurePosixPath(logical_path).suffix.lower()
    if extension not in MIME_BY_EXTENSION:
        raise ApiProblem(
            415,
            "unsupported_project_file",
            "지원하지 않는 Project 파일 형식입니다.",
        )
    mime_type = sniff_mime(content, extension)
    if mime_type != MIME_BY_EXTENSION[extension]:
        raise ApiProblem(
            415,
            "mime_mismatch",
            "파일 내용과 경로의 확장자가 일치하지 않습니다.",
        )
    extraction = extract_attachment_text(
        filename=PurePosixPath(logical_path).name,
        mime_type=mime_type,
        content=content,
    )
    if extraction.status == "failed":
        raise ApiProblem(
            422,
            "project_file_extraction_failed",
            "Project 파일 내용을 안전하게 읽을 수 없습니다.",
            details={"errorType": extraction.metadata.get("errorType", "Unknown")},
        )
    if not mime_type.startswith("image/") and extraction.status == "unsupported":
        raise ApiProblem(
            415,
            "project_file_extraction_unsupported",
            "이 Project 파일 형식의 내용 추출을 지원하지 않습니다.",
        )
    return PreparedProjectFile(
        content=content,
        content_hash=hashlib.sha256(content).hexdigest(),
        extension=extension,
        mime_type=mime_type,
        extraction_status=extraction.status,
        extraction_text=extraction.text,
        locator_map=extraction.locator_map,
        extraction_metadata=extraction.metadata,
    )


def create_project_file(
    db: Session,
    *,
    user: User,
    project_id: str,
    logical_path: str,
    original_filename: str,
    content: bytes,
    change_reason: str,
    max_upload_bytes: int,
    storage: ManagedStorage,
) -> tuple[ProjectFile, ProjectFileVersion]:
    project = require_project(db, user, project_id, write=True)
    canonical_path = normalize_logical_path(logical_path)
    prepared = prepare_project_file(
        logical_path=canonical_path,
        content=content,
        max_upload_bytes=max_upload_bytes,
    )
    active_path_key = logical_path_key(canonical_path)
    duplicate = db.scalar(
        select(ProjectFile.id).where(
            ProjectFile.project_id == project.id,
            ProjectFile.active_path_key == active_path_key,
        )
    )
    if duplicate is not None:
        raise ApiProblem(
            409,
            "project_file_path_exists",
            "같은 경로의 Project 파일이 이미 있습니다.",
        )
    folder_collision = db.scalar(
        select(ProjectFolder.id).where(
            ProjectFolder.project_id == project.id,
            ProjectFolder.active_path_key == active_path_key,
        )
    )
    if folder_collision is not None:
        raise ApiProblem(
            409,
            "project_file_path_exists",
            "같은 경로의 Project 폴더가 이미 있습니다.",
        )

    file_id = new_uuid()
    version_id = new_uuid()
    version_number = 1
    stored = _store_version_content(
        storage,
        project_id=project.id,
        file_id=file_id,
        version_id=version_id,
        version_number=version_number,
        prepared=prepared,
    )
    extraction_metadata = dict(prepared.extraction_metadata)
    try:
        _store_extraction(
            storage,
            project_id=project.id,
            file_id=file_id,
            version_id=version_id,
            prepared=prepared,
            metadata=extraction_metadata,
        )
    except StorageError:
        _cleanup_storage(storage, stored.key)
        raise
    now = utc_now()
    project_file = ProjectFile(
        id=file_id,
        organization_id=project.organization_id,
        project_id=project.id,
        created_by_user_id=user.id,
        logical_path=canonical_path,
        active_path_key=active_path_key,
        current_version_number=version_number,
        revision=1,
        status="active",
        created_at=now,
        updated_at=now,
    )
    version = ProjectFileVersion(
        id=version_id,
        project_file_id=file_id,
        version_number=version_number,
        storage_backend="local",
        storage_key=stored.key,
        content_hash=prepared.content_hash,
        size_bytes=len(content),
        mime_type=prepared.mime_type,
        original_filename=original_filename,
        extraction_status=prepared.extraction_status,
        extraction_version=EXTRACTION_VERSION,
        locator_map_json=prepared.locator_map,
        metadata_json=extraction_metadata,
        change_reason=change_reason or None,
        created_by_user_id=user.id,
        created_at=now,
    )
    try:
        db.add_all((project_file, version))
        db.flush()
    except IntegrityError as exc:
        _cleanup_storage(
            storage,
            stored.key,
            extraction_metadata.get("extractedStorageKey"),
        )
        db.rollback()
        raise ApiProblem(
            409,
            "project_file_path_exists",
            "같은 경로의 Project 파일이 이미 있습니다.",
        ) from exc
    except BaseException:
        _cleanup_storage(
            storage,
            stored.key,
            extraction_metadata.get("extractedStorageKey"),
        )
        raise
    return project_file, version


def create_project_file_version(
    db: Session,
    *,
    user: User,
    project_id: str,
    file_id: str,
    base_version: int,
    original_filename: str,
    content: bytes,
    change_reason: str,
    source_run_id: str | None,
    max_upload_bytes: int,
    storage: ManagedStorage,
) -> tuple[ProjectFile, ProjectFileVersion]:
    project_file = get_project_file(db, user, project_id, file_id, write=True)
    stable_file_id = project_file.id
    if source_run_id is not None:
        source_run = db.get(Run, source_run_id)
        if source_run is None or source_run.project_id != project_id:
            raise ApiProblem(
                404, "source_run_not_found", "원본 Run을 찾을 수 없습니다."
            )
        require_conversation(db, user, source_run.conversation_id)
    if project_file.current_version_number != base_version:
        raise _version_conflict(project_file.current_version_number)
    prepared = prepare_project_file(
        logical_path=project_file.logical_path,
        content=content,
        max_upload_bytes=max_upload_bytes,
    )
    current = get_project_file_version(db, project_file, base_version)
    if current.content_hash == prepared.content_hash:
        raise ApiProblem(
            409,
            "project_file_content_unchanged",
            "현재 버전과 내용이 같아 새 버전을 만들지 않았습니다.",
        )

    next_version = base_version + 1
    version_id = new_uuid()
    stored = _store_version_content(
        storage,
        project_id=project_id,
        file_id=project_file.id,
        version_id=version_id,
        version_number=next_version,
        prepared=prepared,
    )
    extraction_metadata = dict(prepared.extraction_metadata)
    try:
        _store_extraction(
            storage,
            project_id=project_id,
            file_id=project_file.id,
            version_id=version_id,
            prepared=prepared,
            metadata=extraction_metadata,
        )
    except StorageError:
        _cleanup_storage(storage, stored.key)
        raise
    now = utc_now()
    try:
        result = db.execute(
            update(ProjectFile)
            .where(
                ProjectFile.id == project_file.id,
                ProjectFile.current_version_number == base_version,
                ProjectFile.deleted_at.is_(None),
            )
            .values(
                current_version_number=next_version,
                revision=ProjectFile.revision + 1,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
    except BaseException:
        _cleanup_storage(
            storage,
            stored.key,
            extraction_metadata.get("extractedStorageKey"),
        )
        raise
    if getattr(result, "rowcount", 0) != 1:
        _cleanup_storage(
            storage,
            stored.key,
            extraction_metadata.get("extractedStorageKey"),
        )
        db.rollback()
        current_version = db.scalar(
            select(ProjectFile.current_version_number).where(
                ProjectFile.id == stable_file_id
            )
        )
        raise _version_conflict(int(current_version or base_version))
    version = ProjectFileVersion(
        id=version_id,
        project_file_id=project_file.id,
        version_number=next_version,
        storage_backend="local",
        storage_key=stored.key,
        content_hash=prepared.content_hash,
        size_bytes=len(content),
        mime_type=prepared.mime_type,
        original_filename=original_filename,
        parent_version_id=current.id,
        source_run_id=source_run_id,
        extraction_status=prepared.extraction_status,
        extraction_version=EXTRACTION_VERSION,
        locator_map_json=prepared.locator_map,
        metadata_json=extraction_metadata,
        change_reason=change_reason or None,
        created_by_user_id=user.id,
        created_at=now,
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError as exc:
        _cleanup_storage(
            storage,
            stored.key,
            extraction_metadata.get("extractedStorageKey"),
        )
        db.rollback()
        raise _version_conflict(base_version) from exc
    except BaseException:
        _cleanup_storage(
            storage,
            stored.key,
            extraction_metadata.get("extractedStorageKey"),
        )
        raise
    try:
        db.expire(project_file)
        db.refresh(project_file)
    except BaseException:
        _cleanup_storage(
            storage,
            stored.key,
            extraction_metadata.get("extractedStorageKey"),
        )
        raise
    return project_file, version


def move_project_file(
    db: Session,
    *,
    user: User,
    project_id: str,
    file_id: str,
    logical_path: str,
    expected_revision: int,
) -> ProjectFile:
    project_file = get_project_file(db, user, project_id, file_id, write=True)
    stable_file_id = project_file.id
    canonical_path = normalize_logical_path(logical_path)
    current_version = get_project_file_version(db, project_file)
    target_extension = PurePosixPath(canonical_path).suffix.lower()
    if MIME_BY_EXTENSION.get(target_extension) != current_version.mime_type:
        raise ApiProblem(
            409,
            "project_file_extension_mismatch",
            "파일 형식을 바꾸려면 새 파일로 저장해 주세요.",
        )
    active_path_key = logical_path_key(canonical_path)
    if project_file.revision != expected_revision:
        raise _revision_conflict(project_file.revision)
    if project_file.logical_path == canonical_path:
        return project_file
    duplicate = db.scalar(
        select(ProjectFile.id).where(
            ProjectFile.project_id == project_id,
            ProjectFile.active_path_key == active_path_key,
            ProjectFile.id != project_file.id,
        )
    )
    if duplicate is not None:
        raise ApiProblem(
            409,
            "project_file_path_exists",
            "같은 경로의 Project 파일이 이미 있습니다.",
        )
    folder_collision = db.scalar(
        select(ProjectFolder.id).where(
            ProjectFolder.project_id == project_id,
            ProjectFolder.active_path_key == active_path_key,
        )
    )
    if folder_collision is not None:
        raise ApiProblem(
            409,
            "project_file_path_exists",
            "같은 경로의 Project 폴더가 이미 있습니다.",
        )
    result = db.execute(
        update(ProjectFile)
        .where(
            ProjectFile.id == project_file.id,
            ProjectFile.revision == expected_revision,
            ProjectFile.deleted_at.is_(None),
        )
        .values(
            logical_path=canonical_path,
            active_path_key=active_path_key,
            revision=expected_revision + 1,
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        db.rollback()
        current_revision = db.scalar(
            select(ProjectFile.revision).where(ProjectFile.id == stable_file_id)
        )
        raise _revision_conflict(int(current_revision or expected_revision))
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ApiProblem(
            409,
            "project_file_path_exists",
            "같은 경로의 Project 파일이 이미 있습니다.",
        ) from exc
    db.expire(project_file)
    db.refresh(project_file)
    return project_file


def soft_delete_project_file(
    db: Session,
    *,
    user: User,
    project_id: str,
    file_id: str,
    expected_revision: int,
) -> ProjectFile:
    project_file = get_project_file(db, user, project_id, file_id, write=True)
    stable_file_id = project_file.id
    if project_file.revision != expected_revision:
        raise _revision_conflict(project_file.revision)
    now = utc_now()
    result = db.execute(
        update(ProjectFile)
        .where(
            ProjectFile.id == project_file.id,
            ProjectFile.revision == expected_revision,
            ProjectFile.deleted_at.is_(None),
        )
        .values(
            active_path_key=None,
            status="deleted",
            deleted_at=now,
            revision=expected_revision + 1,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        db.rollback()
        current_revision = db.scalar(
            select(ProjectFile.revision).where(ProjectFile.id == stable_file_id)
        )
        raise _revision_conflict(int(current_revision or expected_revision))
    db.flush()
    db.expire(project_file)
    db.refresh(project_file)
    return project_file


def _store_version_content(
    storage: ManagedStorage,
    *,
    project_id: str,
    file_id: str,
    version_id: str,
    version_number: int,
    prepared: PreparedProjectFile,
) -> StoredObject:
    key = (
        f"project-files/{project_id}/{file_id}/{version_id}/"
        f"v{version_number}-{prepared.content_hash}{prepared.extension}"
    )
    return storage.put_bytes(
        key,
        prepared.content,
        expected_sha256=prepared.content_hash,
    )


def _store_extraction(
    storage: ManagedStorage,
    *,
    project_id: str,
    file_id: str,
    version_id: str,
    prepared: PreparedProjectFile,
    metadata: dict[str, Any],
) -> None:
    if prepared.extraction_status != "completed":
        return
    extracted = prepared.extraction_text.encode("utf-8")
    extracted_digest = hashlib.sha256(extracted).hexdigest()
    key = (
        f"project-file-extractions/{project_id}/{file_id}/{version_id}/"
        f"{extracted_digest}.txt"
    )
    stored = storage.put_bytes(key, extracted, expected_sha256=extracted_digest)
    metadata.update(
        {
            "extractedStorageKey": stored.key,
            "extractedContentHash": extracted_digest,
            "extractedSize": len(extracted),
        }
    )


def _cleanup_storage(storage: ManagedStorage, *keys: object) -> None:
    for key in keys:
        if not isinstance(key, str):
            continue
        try:
            storage.delete(key)
        except StorageError:
            continue


def cleanup_project_file_version_storage(
    storage: ManagedStorage, version: ProjectFileVersion
) -> None:
    _cleanup_storage(
        storage,
        version.storage_key,
        version.metadata_json.get("extractedStorageKey"),
    )


def _version_conflict(current_version: int) -> ApiProblem:
    return ApiProblem(
        409,
        "project_file_version_conflict",
        "Project 파일이 다른 작업에서 변경되었습니다.",
        details={"currentVersion": current_version},
    )


def _revision_conflict(current_revision: int) -> ApiProblem:
    return ApiProblem(
        409,
        "project_file_revision_conflict",
        "Project 파일 정보가 다른 작업에서 변경되었습니다.",
        details={"currentRevision": current_revision},
    )
