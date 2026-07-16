from __future__ import annotations

import base64
import binascii
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...authorization import require_project
from ...db import get_db
from ...extensions.service import resolve_skill_snapshot
from ...mcp.service import resolve_mcp_snapshot
from ...project_files.folders import build_project_folder_references
from ...models import (
    Artifact,
    ArtifactVersion,
    Attachment,
    ProjectFile,
    ProjectFileVersion,
    User,
)
from ..dependencies import get_current_user
from ..errors import ApiProblem


router = APIRouter(prefix="/composer", tags=["composer"])


@router.get("/suggestions")
def get_composer_suggestions(
    project_id: str,
    trigger: Literal["@", "$"],
    query: str = Query(default="", max_length=200),
    cursor: str | None = None,
    limit: int = Query(default=12, ge=1, le=30),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = require_project(db, user, project_id)
    tokens = query.casefold().split()
    candidates = (
        _context_candidates(db, project.id)
        if trigger == "@"
        else _extension_candidates(db, user, project.id)
    )
    if tokens:
        candidates = [
            item
            for item in candidates
            if all(
                token
                in " ".join(
                    (
                        str(item.get("name", "")),
                        str(item.get("subtitle", "")),
                        str(item.get("kind", "")),
                    )
                ).casefold()
                for token in tokens
            )
        ]
    offset = _decode_cursor(cursor) if cursor else 0
    if offset > len(candidates):
        raise ApiProblem(400, "invalid_cursor", "Composer cursor가 만료되었습니다.")
    items = candidates[offset : offset + limit]
    next_offset = offset + len(items)
    has_more = next_offset < len(candidates)
    return {
        "items": items,
        "nextCursor": _encode_cursor(next_offset) if has_more else None,
        "hasMore": has_more,
    }


def _context_candidates(db: Session, project_id: str) -> list[dict[str, Any]]:
    workspace_rows = list(
        db.execute(
            select(ProjectFile, ProjectFileVersion)
            .join(
                ProjectFileVersion,
                (ProjectFileVersion.project_file_id == ProjectFile.id)
                & (
                    ProjectFileVersion.version_number
                    == ProjectFile.current_version_number
                ),
            )
            .where(
                ProjectFile.project_id == project_id,
                ProjectFile.deleted_at.is_(None),
                ProjectFile.status == "active",
            )
            .order_by(ProjectFile.updated_at.desc(), ProjectFile.id)
            .limit(500)
        ).tuples()
    )
    attachments = list(
        db.scalars(
            select(Attachment)
            .where(
                Attachment.project_id == project_id,
                Attachment.deleted_at.is_(None),
                Attachment.status.in_(("ready", "completed")),
            )
            .order_by(Attachment.created_at.desc(), Attachment.id)
            .limit(100)
        )
    )
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.deleted_at.is_(None))
            .order_by(Artifact.updated_at.desc(), Artifact.id)
            .limit(100)
        )
    )
    folder_items: list[dict[str, Any]] = [
        {
            "id": folder.id,
            "referenceId": folder.id,
            "kind": "folder",
            "name": folder.name,
            "displayName": folder.name,
            "subtitle": f"{folder.logical_path} · {len(folder.file_versions)}개 파일",
            "description": "하위 파일 전체를 Context로 참조",
            "insertText": f"@{folder.name}",
            "status": "available",
            "versionOrDigest": folder.content_hash,
            "projectId": project_id,
            "scope": {"type": "project", "id": project_id},
            "displaySnapshot": {
                "name": folder.name,
                "targetType": "project_folder",
                "logicalPath": folder.logical_path,
                "fileCount": len(folder.file_versions),
                "fileVersions": list(folder.file_versions),
                "contentHash": folder.content_hash,
            },
        }
        for folder in build_project_folder_references(project_id, workspace_rows)
    ]
    workspace_items: list[dict[str, Any]] = [
        {
            "id": project_file.id,
            "referenceId": project_file.id,
            "kind": "file",
            "name": project_file.logical_path.rsplit("/", 1)[-1],
            "displayName": project_file.logical_path.rsplit("/", 1)[-1],
            "subtitle": project_file.logical_path,
            "description": f"사용자 파일 · {version.mime_type}",
            "insertText": f"@{project_file.logical_path.rsplit('/', 1)[-1]}",
            "status": "available",
            "versionOrDigest": version.content_hash,
            "projectId": project_id,
            "scope": {"type": "project", "id": project_id},
            "displaySnapshot": {
                "name": project_file.logical_path.rsplit("/", 1)[-1],
                "targetType": "project_file",
                "logicalPath": project_file.logical_path,
                "mimeType": version.mime_type,
                "version": version.version_number,
                "versionId": version.id,
                "contentHash": version.content_hash,
            },
        }
        for project_file, version in workspace_rows
    ]
    attachment_items: list[dict[str, Any]] = [
        {
            "id": attachment.id,
            "referenceId": attachment.id,
            "kind": "file",
            "name": attachment.original_filename,
            "displayName": attachment.original_filename,
            "subtitle": attachment.sniffed_mime_type,
            "description": attachment.sniffed_mime_type,
            "insertText": f"@{attachment.original_filename}",
            "status": "available",
            "versionOrDigest": attachment.content_hash,
            "projectId": project_id,
            "scope": {"type": "project", "id": project_id},
            "displaySnapshot": {
                "name": attachment.original_filename,
                "targetType": "attachment",
                "mimeType": attachment.sniffed_mime_type,
                "contentHash": attachment.content_hash,
            },
        }
        for attachment in attachments
    ]
    artifact_items: list[dict[str, Any]] = []
    for artifact in artifacts:
        version = db.scalar(
            select(ArtifactVersion).where(
                ArtifactVersion.artifact_id == artifact.id,
                ArtifactVersion.version_number == artifact.current_version_number,
            )
        )
        if version is None:
            continue
        artifact_items.append(
            {
                "id": artifact.id,
                "referenceId": artifact.id,
                "kind": "artifact",
                "name": artifact.display_name,
                "displayName": artifact.display_name,
                "subtitle": f"{artifact.kind.upper()} · v{version.version_number}",
                "description": f"{artifact.kind.upper()} · v{version.version_number}",
                "insertText": f"@{artifact.display_name}",
                "status": "available",
                "versionOrDigest": version.content_hash,
                "projectId": project_id,
                "scope": {"type": "project", "id": project_id},
                "displaySnapshot": {
                    "name": artifact.display_name,
                    "kind": artifact.kind,
                    "version": version.version_number,
                    "contentHash": version.content_hash,
                },
            }
        )

    def sort_key(item: dict[str, Any]) -> tuple[str, str]:
        return str(item["name"]).casefold(), str(item["id"])

    return [
        *sorted(folder_items, key=sort_key),
        *sorted(workspace_items, key=sort_key),
        *sorted(attachment_items, key=sort_key),
        *sorted(artifact_items, key=sort_key),
    ]


def _skill_candidates(db: Session, user: User, project_id: str) -> list[dict[str, Any]]:
    items = []
    for snapshot in resolve_skill_snapshot(db, user=user, project_id=project_id):
        draft_revision = snapshot.get("draft_revision")
        version = snapshot.get("version")
        label = (
            f"Draft r{draft_revision} · 저장 안 됨"
            if draft_revision is not None
            else f"v{version}"
        )
        items.append(
            {
                "id": snapshot["extension_id"],
                "referenceId": snapshot["extension_id"],
                "kind": snapshot.get("kind", "skill"),
                "name": snapshot["name"],
                "displayName": snapshot["name"],
                "subtitle": label,
                "description": snapshot.get("description", ""),
                "insertText": (
                    f"${snapshot.get('kind', 'skill')}:{snapshot.get('slug', snapshot['name'])}"
                ),
                "status": "available",
                "versionOrDigest": snapshot["digest"],
                "projectId": project_id,
                "scope": {
                    "type": snapshot.get("scope_type", "user"),
                    "id": snapshot.get("scope_id", user.id),
                },
                "displaySnapshot": {
                    "name": snapshot["name"],
                    "kind": snapshot.get("kind", "skill"),
                    "slug": snapshot.get("slug"),
                    "source": snapshot["source"],
                    "draftRevision": draft_revision,
                    "draftId": snapshot.get("draft_id"),
                    "version": version,
                    "versionId": snapshot.get("version_id"),
                    "digest": snapshot["digest"],
                },
            }
        )
    return items


def _extension_candidates(
    db: Session, user: User, project_id: str
) -> list[dict[str, Any]]:
    items = _skill_candidates(db, user, project_id)
    for snapshot in resolve_mcp_snapshot(db, user=user, project_id=project_id):
        label = (
            f"MCP r{snapshot['configuration_revision']} · "
            f"{len(snapshot['tool_allowlist'])}개 Tool"
        )
        items.append(
            {
                "id": snapshot["definition_id"],
                "referenceId": snapshot["definition_id"],
                "kind": "mcp",
                "name": snapshot["name"],
                "displayName": snapshot["name"],
                "subtitle": label,
                "description": snapshot.get("description", ""),
                "insertText": f"$mcp:{snapshot['slug']}",
                "status": "available",
                "versionOrDigest": snapshot["digest"],
                "projectId": project_id,
                "scope": {
                    "type": snapshot["scope_type"],
                    "id": snapshot["scope_id"],
                },
                "displaySnapshot": {
                    "name": snapshot["name"],
                    "kind": "mcp",
                    "slug": snapshot["slug"],
                    "configurationRevisionId": snapshot["configuration_revision_id"],
                    "configurationRevision": snapshot["configuration_revision"],
                    "digest": snapshot["digest"],
                    "toolAllowlist": snapshot["tool_allowlist"],
                    "healthStatus": snapshot["health_status"],
                    "schemaStatus": snapshot["schema_status"],
                },
            }
        )
    return sorted(items, key=lambda item: (str(item["name"]).casefold(), item["id"]))


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> int:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = int(base64.urlsafe_b64decode(padded).decode())
        if value < 0:
            raise ValueError("negative offset")
        return value
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ApiProblem(
            400, "invalid_cursor", "Composer cursor가 올바르지 않습니다."
        ) from exc
