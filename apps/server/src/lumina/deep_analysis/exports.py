from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ProjectFile, ProjectFileVersion, User, utc_now
from ..project_files import (
    cleanup_project_file_version_storage,
    create_project_file,
    create_project_folder,
)
from ..storage import ManagedStorage
from .models import (
    DeepAnalysisMission,
    DeepAnalysisMissionExport,
    DeepAnalysisWorkflowNode,
)
from .service import active_workflow


_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_EXPORT_TIMEZONE = ZoneInfo("Asia/Seoul")


def _safe_name(value: str, fallback: str) -> str:
    clean = _UNSAFE_FILENAME.sub("_", value).strip().strip(".")
    return clean[:180] or fallback


def _current_file_version(
    db: Session, *, project_id: str, project_file_id: str
) -> tuple[ProjectFile, ProjectFileVersion] | None:
    return db.execute(
        select(ProjectFile, ProjectFileVersion)
        .join(ProjectFileVersion, ProjectFileVersion.project_file_id == ProjectFile.id)
        .where(
            ProjectFile.id == project_file_id,
            ProjectFile.project_id == project_id,
            ProjectFile.deleted_at.is_(None),
            ProjectFileVersion.version_number == ProjectFile.current_version_number,
        )
    ).one_or_none()


def _source_file_version(
    db: Session, *, project_id: str, project_file_id: str, version_id: str
) -> tuple[ProjectFile, ProjectFileVersion] | None:
    return db.execute(
        select(ProjectFile, ProjectFileVersion)
        .join(ProjectFileVersion, ProjectFileVersion.project_file_id == ProjectFile.id)
        .where(
            ProjectFile.id == project_file_id,
            ProjectFile.project_id == project_id,
            ProjectFileVersion.id == version_id,
        )
    ).one_or_none()


def _unique_name(used_names: set[str], *, name: str, project_file_id: str) -> str:
    candidate = _safe_name(name, project_file_id)
    key = candidate.casefold()
    if key not in used_names:
        used_names.add(key)
        return candidate
    candidate = f"{project_file_id[:8]}_{candidate}"
    used_names.add(candidate.casefold())
    return candidate


def _generated_file_ids(nodes: list[DeepAnalysisWorkflowNode]) -> set[str]:
    file_ids: set[str] = set()
    for node in nodes:
        if node.output_project_file_id:
            file_ids.add(node.output_project_file_id)
        file_ids.update(
            str(item.get("projectFileId"))
            for item in node.generated_files_json
            if item.get("projectFileId")
        )
    return file_ids


def create_mission_export(
    db: Session,
    storage: ManagedStorage,
    *,
    mission: DeepAnalysisMission,
    user: User,
    max_upload_bytes: int,
    requested_at: datetime,
) -> DeepAnalysisMissionExport:
    export = DeepAnalysisMissionExport(
        mission_id=mission.id,
        requested_by_user_id=user.id,
        scope="latest",
        include_originals=True,
        status="preparing",
    )
    db.add(export)
    db.flush()

    timestamp = requested_at.astimezone(_EXPORT_TIMEZONE).strftime("%y%m%d_%H%M%S")
    folder_path = f"Mission 내보내기/{_safe_name(mission.title, 'Mission')}_{timestamp}"
    create_project_folder(
        db,
        user=user,
        project_id=mission.project_id,
        logical_path=folder_path,
    )

    _revision, nodes, _edges = active_workflow(db, mission.id)
    generated_rows = [
        row
        for file_id in sorted(_generated_file_ids(nodes))
        if (
            row := _current_file_version(
                db, project_id=mission.project_id, project_file_id=file_id
            )
        )
        is not None
    ]
    source_rows = [
        row
        for source in mission.source_manifest_json
        if (file_id := str(source.get("projectFileId") or ""))
        and (version_id := str(source.get("versionId") or ""))
        and (
            row := _source_file_version(
                db,
                project_id=mission.project_id,
                project_file_id=file_id,
                version_id=version_id,
            )
        )
        is not None
    ]

    created_versions: list[ProjectFileVersion] = []
    exported_paths: list[str] = []
    used_generated_names: set[str] = set()
    used_source_names: set[str] = set()
    total_size = 0
    try:
        for category, rows, used_names in (
            ("생성 파일", generated_rows, used_generated_names),
            ("원본 자료", source_rows, used_source_names),
        ):
            for project_file, version in rows:
                name = _unique_name(
                    used_names,
                    name=PurePosixPath(project_file.logical_path).name,
                    project_file_id=project_file.id,
                )
                logical_path = f"{folder_path}/{category}/{name}"
                content = storage.read_bytes(
                    version.storage_key, expected_sha256=version.content_hash
                )
                _, created_version = create_project_file(
                    db,
                    user=user,
                    project_id=mission.project_id,
                    logical_path=logical_path,
                    original_filename=name,
                    content=content,
                    change_reason=f"Mission 내보내기: {mission.title}",
                    max_upload_bytes=max_upload_bytes,
                    storage=storage,
                )
                created_versions.append(created_version)
                exported_paths.append(logical_path)
                total_size += created_version.size_bytes
    except BaseException:
        for version in created_versions:
            cleanup_project_file_version_storage(storage, version)
        raise

    export.status = "completed"
    export.filename = folder_path
    export.content_hash = None
    export.size_bytes = total_size
    export.manifest_json = {
        "folderPath": folder_path,
        "generatedFileCount": len(generated_rows),
        "sourceFileCount": len(source_rows),
        "fileCount": len(exported_paths),
        "files": exported_paths,
        "scope": "latest",
        "includeOriginals": True,
    }
    export.completed_at = utc_now()
    db.flush()
    return export
