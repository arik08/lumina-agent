from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem
from ..authorization import require_project
from ..models import ProjectFile, ProjectFileVersion, ProjectFolder, User, utc_now
from .service import logical_path_key, normalize_logical_path


FOLDER_REFERENCE_NAMESPACE = UUID("7ad2df37-a2f5-4a48-a9a0-b9d644c79c5f")


@dataclass(frozen=True)
class ProjectFolderReference:
    id: str
    logical_path: str
    content_hash: str
    file_versions: tuple[dict[str, str], ...]

    @property
    def name(self) -> str:
        return PurePosixPath(self.logical_path).name


def list_project_folders(
    db: Session, user: User, project_id: str
) -> list[ProjectFolder]:
    require_project(db, user, project_id)
    return list(
        db.scalars(
            select(ProjectFolder)
            .where(
                ProjectFolder.project_id == project_id,
                ProjectFolder.status == "active",
                ProjectFolder.deleted_at.is_(None),
            )
            .order_by(ProjectFolder.logical_path, ProjectFolder.id)
        )
    )


def create_project_folder(
    db: Session,
    *,
    user: User,
    project_id: str,
    logical_path: str,
) -> ProjectFolder:
    project = require_project(db, user, project_id, write=True)
    canonical_path = normalize_logical_path(logical_path)
    path_key = logical_path_key(canonical_path)
    active_files, active_folders = _active_project_entries(db, project_id)
    if any(
        _is_same_or_descendant(item.logical_path, canonical_path)
        for item in [*active_files, *active_folders]
    ):
        raise ApiProblem(
            409,
            "project_folder_path_exists",
            "같은 경로의 폴더 또는 파일이 이미 있습니다.",
        )
    folder = ProjectFolder(
        organization_id=project.organization_id,
        project_id=project.id,
        created_by_user_id=user.id,
        logical_path=canonical_path,
        active_path_key=path_key,
    )
    db.add(folder)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ApiProblem(
            409,
            "project_folder_path_exists",
            "같은 경로의 폴더 또는 파일이 이미 있습니다.",
        ) from exc
    return folder


def move_project_folder(
    db: Session,
    *,
    user: User,
    project_id: str,
    source_path: str,
    target_path: str,
) -> tuple[int, int]:
    require_project(db, user, project_id, write=True)
    source = normalize_logical_path(source_path)
    target = normalize_logical_path(target_path)
    if logical_path_key(source) == logical_path_key(target):
        return (0, 0)
    if _is_same_or_descendant(target, source):
        raise ApiProblem(
            422,
            "invalid_project_folder_target",
            "폴더를 자기 하위로 이동할 수 없습니다.",
        )

    active_files, active_folders = _active_project_entries(db, project_id)
    moving_files = [item for item in active_files if _is_same_or_descendant(item.logical_path, source)]
    moving_folders = [item for item in active_folders if _is_same_or_descendant(item.logical_path, source)]
    if not moving_files and not moving_folders:
        raise ApiProblem(404, "project_folder_not_found", "Project 폴더를 찾지 못했습니다.")

    file_targets = {item.id: _replace_path_prefix(item.logical_path, source, target) for item in moving_files}
    folder_targets = {item.id: _replace_path_prefix(item.logical_path, source, target) for item in moving_folders}
    moving_file_ids = set(file_targets)
    moving_folder_ids = set(folder_targets)
    occupied_file_keys = {
        logical_path_key(item.logical_path)
        for item in active_files
        if item.id not in moving_file_ids
    }
    occupied_folder_keys = {
        logical_path_key(item.logical_path)
        for item in active_folders
        if item.id not in moving_folder_ids
    }
    target_file_keys = {logical_path_key(path) for path in file_targets.values()}
    target_folder_keys = {logical_path_key(path) for path in folder_targets.values()}
    if (
        len(target_file_keys) != len(file_targets)
        or len(target_folder_keys) != len(folder_targets)
        or target_file_keys & (occupied_file_keys | occupied_folder_keys | target_folder_keys)
        or target_folder_keys & occupied_file_keys
    ):
        raise ApiProblem(
            409,
            "project_folder_target_exists",
            "이동할 위치에 같은 이름의 파일 또는 폴더가 이미 있습니다.",
        )

    now = utc_now()
    for item in moving_files:
        item.logical_path = file_targets[item.id]
        item.active_path_key = logical_path_key(item.logical_path)
        item.revision += 1
        item.updated_at = now
    for item in moving_folders:
        item.logical_path = folder_targets[item.id]
        item.active_path_key = logical_path_key(item.logical_path)
        item.revision += 1
        item.updated_at = now
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ApiProblem(
            409,
            "project_folder_target_exists",
            "이동할 위치에 같은 이름의 파일 또는 폴더가 이미 있습니다.",
        ) from exc
    return (len(moving_files), len(moving_folders))


def soft_delete_project_folder(
    db: Session,
    *,
    user: User,
    project_id: str,
    logical_path: str,
) -> tuple[int, int]:
    require_project(db, user, project_id, write=True)
    canonical_path = normalize_logical_path(logical_path)
    active_files, active_folders = _active_project_entries(db, project_id)
    deleting_files = [item for item in active_files if _is_same_or_descendant(item.logical_path, canonical_path)]
    deleting_folders = [item for item in active_folders if _is_same_or_descendant(item.logical_path, canonical_path)]
    if not deleting_files and not deleting_folders:
        raise ApiProblem(404, "project_folder_not_found", "Project 폴더를 찾지 못했습니다.")
    now = utc_now()
    for item in [*deleting_files, *deleting_folders]:
        item.active_path_key = None
        item.status = "deleted"
        item.deleted_at = now
        item.revision += 1
        item.updated_at = now
    db.flush()
    return (len(deleting_files), len(deleting_folders))


def _active_project_entries(
    db: Session, project_id: str
) -> tuple[list[ProjectFile], list[ProjectFolder]]:
    files = list(
        db.scalars(
            select(ProjectFile).where(
                ProjectFile.project_id == project_id,
                ProjectFile.status == "active",
                ProjectFile.deleted_at.is_(None),
            )
        )
    )
    folders = list(
        db.scalars(
            select(ProjectFolder).where(
                ProjectFolder.project_id == project_id,
                ProjectFolder.status == "active",
                ProjectFolder.deleted_at.is_(None),
            )
        )
    )
    return files, folders


def _is_same_or_descendant(path: str, parent: str) -> bool:
    path_parts = tuple(part.casefold() for part in PurePosixPath(path).parts)
    parent_parts = tuple(part.casefold() for part in PurePosixPath(parent).parts)
    return path_parts[: len(parent_parts)] == parent_parts


def _replace_path_prefix(path: str, source: str, target: str) -> str:
    path_parts = PurePosixPath(path).parts
    source_parts = PurePosixPath(source).parts
    suffix = path_parts[len(source_parts) :]
    return PurePosixPath(target, *suffix).as_posix()


def build_project_folder_references(
    project_id: str,
    rows: Iterable[tuple[ProjectFile, ProjectFileVersion]],
) -> list[ProjectFolderReference]:
    folders: dict[str, list[dict[str, str]]] = {}
    for project_file, version in rows:
        parts = PurePosixPath(project_file.logical_path).parts
        file_version = {
            "id": project_file.id,
            "path": project_file.logical_path,
            "digest": version.content_hash,
        }
        for depth in range(1, len(parts)):
            folder_path = PurePosixPath(*parts[:depth]).as_posix()
            folders.setdefault(folder_path, []).append(file_version)

    references: list[ProjectFolderReference] = []
    for folder_path, file_versions in folders.items():
        ordered = tuple(
            sorted(file_versions, key=lambda item: (item["path"].casefold(), item["id"]))
        )
        digest_source = "\n".join(
            f'{item["path"]}\0{item["digest"]}' for item in ordered
        ).encode("utf-8")
        references.append(
            ProjectFolderReference(
                id=str(
                    uuid5(
                        FOLDER_REFERENCE_NAMESPACE,
                        f"{project_id}\0{folder_path.casefold()}",
                    )
                ),
                logical_path=folder_path,
                content_hash=hashlib.sha256(digest_source).hexdigest(),
                file_versions=ordered,
            )
        )
    return sorted(
        references,
        key=lambda item: (item.logical_path.casefold(), item.id),
    )


__all__ = [
    "ProjectFolderReference",
    "build_project_folder_references",
    "create_project_folder",
    "list_project_folders",
    "move_project_folder",
    "soft_delete_project_folder",
]
