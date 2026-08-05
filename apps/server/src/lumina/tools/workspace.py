from __future__ import annotations

import fnmatch
import hashlib
import re
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..extensions.service import sync_workspace_skill
from ..models import ProjectFile, ProjectFileVersion, Run, User
from ..project_files.service import (
    create_project_file,
    create_project_file_version,
    get_project_file_version,
    normalize_logical_path,
    soft_delete_project_file,
)
from ..storage import ManagedStorage


MAX_RESULTS = 200
MAX_READ_LINES = 2_000
MAX_READ_CHARS = 100_000
MAX_GREP_FILE_CHARS = 1_000_000
SKILL_WORKSPACE_ROOT = ("extensions", "skills")
_SKILL_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
ARTIFACT_WRITE_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": (
            "Create or revise a user-requested UTF-8 Artifact without writing to the "
            "user-managed Project file repository. Use it for source code, executable HTML "
            "apps, demos, and games. To revise a file listed in the recent Artifact context, "
            "pass its exact destination_artifact_id so Lumina saves a new immutable version "
            "of that Artifact instead of creating a duplicate."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 1000},
                "content": {"type": "string"},
                "destination_artifact_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 64,
                    "description": (
                        "Exact ID from the recent Artifact context when revising an existing "
                        "file. Omit only when the user requested a separate new file."
                    ),
                },
                "destination_base_version": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Current version from the Artifact context. Required with "
                        "destination_artifact_id so stale edits fail instead of overwriting a "
                        "newer version."
                    ),
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
}


WORKSPACE_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Find files in the current Project workspace by glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "minLength": 1, "maxLength": 500},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_RESULTS,
                        "default": 100,
                    },
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search UTF-8 text files in the current Project workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "path": {"type": "string", "maxLength": 1000, "default": ""},
                    "glob": {"type": "string", "maxLength": 500, "default": "**/*"},
                    "case_sensitive": {"type": "boolean", "default": False},
                    "regex": {"type": "boolean", "default": False},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_RESULTS,
                        "default": 100,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file from the current Project workspace with line pagination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "offset": {"type": "integer", "minimum": 1, "default": 1},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_READ_LINES,
                        "default": 500,
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List direct children of a directory in the current Project workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "maxLength": 1000, "default": ""},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_RESULTS,
                        "default": 100,
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_skill",
            "description": (
                "Create or immediately revise a Lumina Skill Working Draft and persist its "
                "complete package in the "
                "current Project workspace under extensions/skills/<slug>/. Use this "
                "instead of .skills/, a generic file Artifact, or run_python when the user "
                "asks to create or modify a Skill. For a revision, read the current package "
                "first and submit the complete updated package with the existing slug. The "
                "updated Draft becomes the owner's active Skill revision for subsequent Runs; "
                "do not create an Artifact version for a Skill change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                        "maxLength": 64,
                    },
                    "name": {"type": "string", "minLength": 1, "maxLength": 200},
                    "description": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1024,
                    },
                    "files": {
                        "type": "object",
                        "description": (
                            "Skill package files keyed by paths relative to the Skill root. "
                            "SKILL.md is required."
                        ),
                        "minProperties": 1,
                        "maxProperties": 200,
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["slug", "name", "description", "files"],
                "additionalProperties": False,
            },
        },
    },
)


def execute_workspace_tool(
    db: Session,
    storage: ManagedStorage,
    *,
    run: Run,
    user: User,
    name: str,
    arguments: dict[str, Any],
    max_upload_bytes: int,
) -> dict[str, Any]:
    files = _active_files(db, run)
    if name == "glob":
        pattern = _glob_pattern(arguments.get("pattern"))
        limit = _limit(arguments.get("limit", 100))
        matches = [
            item.logical_path for item in files if _matches(item.logical_path, pattern)
        ]
        return _limited_paths(matches, limit)
    if name == "list_dir":
        return _list_dir(
            files, str(arguments.get("path", "")), _limit(arguments.get("limit", 100))
        )
    if name == "read_file":
        item = _require_file(files, arguments.get("path"))
        version = _run_file_version(db, run, item)
        text = _decode_text(
            storage.read_bytes(
                version.storage_key, expected_sha256=version.content_hash
            )
        )
        offset = max(1, int(arguments.get("offset", 1)))
        limit = min(MAX_READ_LINES, max(1, int(arguments.get("limit", 500))))
        lines = text.splitlines()
        selected = lines[offset - 1 : offset - 1 + limit]
        rendered = "\n".join(
            f"{index}|{line}" for index, line in enumerate(selected, offset)
        )
        truncated_by_chars = len(rendered) > MAX_READ_CHARS
        if truncated_by_chars:
            rendered = rendered[:MAX_READ_CHARS]
        next_offset = (
            offset + len(selected) if offset - 1 + len(selected) < len(lines) else None
        )
        return {
            "path": item.logical_path,
            "content": rendered,
            "lineCount": len(lines),
            "nextOffset": next_offset,
            "truncated": bool(next_offset or truncated_by_chars),
        }
    if name == "grep":
        return _grep(db, storage, run, files, arguments)
    if name == "write_file":
        path = normalize_logical_path(str(arguments.get("path", "")))
        content = str(arguments.get("content", "")).encode("utf-8")
        existing = next(
            (item for item in files if item.logical_path.casefold() == path.casefold()),
            None,
        )
        if existing is None:
            item, version = create_project_file(
                db,
                user=user,
                project_id=run.project_id,
                logical_path=path,
                original_filename=PurePosixPath(path).name,
                content=content,
                change_reason="Agent write_file",
                max_upload_bytes=max_upload_bytes,
                storage=storage,
            )
            action = "created"
        else:
            item, version = create_project_file_version(
                db,
                user=user,
                project_id=run.project_id,
                file_id=existing.id,
                base_version=existing.current_version_number,
                original_filename=PurePosixPath(path).name,
                content=content,
                change_reason="Agent write_file",
                source_run_id=run.id,
                max_upload_bytes=max_upload_bytes,
                storage=storage,
            )
            action = "updated"
        result = {
            "projectFileId": item.id,
            "path": item.logical_path,
            "action": action,
            "version": version.version_number,
            "mimeType": version.mime_type,
            "contentHash": version.content_hash,
            "sizeBytes": version.size_bytes,
        }
        skill_draft = _sync_workspace_skill_draft(
            db,
            storage,
            run=run,
            user=user,
            written_path=item.logical_path,
        )
        if skill_draft is not None:
            result["skillDraft"] = skill_draft
        return result
    if name == "create_skill":
        return _create_workspace_skill(
            db,
            storage,
            run=run,
            user=user,
            arguments=arguments,
            max_upload_bytes=max_upload_bytes,
        )
    raise ValueError(f"Unknown workspace tool: {name}")


def _active_files(db: Session, run: Run) -> list[ProjectFile]:
    files = list(
        db.scalars(
            select(ProjectFile)
            .where(
                ProjectFile.project_id == run.project_id, ProjectFile.deleted_at.is_(None)
            )
            .order_by(ProjectFile.logical_path)
        )
    )
    manifest = run.snapshot_json.get("project_file_manifest")
    if not isinstance(manifest, list):
        return files
    allowed_ids = {
        str(item.get("projectFileId"))
        for item in manifest
        if isinstance(item, dict) and item.get("projectFileId")
    }
    return [item for item in files if item.id in allowed_ids]


def _run_file_version(
    db: Session, run: Run, item: ProjectFile
) -> ProjectFileVersion:
    manifest = run.snapshot_json.get("project_file_manifest")
    if isinstance(manifest, list):
        snapshot = next(
            (
                entry
                for entry in manifest
                if isinstance(entry, dict)
                and entry.get("projectFileId") == item.id
            ),
            None,
        )
        if snapshot is not None:
            version = db.get(ProjectFileVersion, str(snapshot.get("versionId") or ""))
            if (
                version is None
                or version.project_file_id != item.id
                or version.content_hash != snapshot.get("contentHash")
            ):
                raise ValueError(f"Frozen Project file version is unavailable: {item.logical_path}")
            return version
    return get_project_file_version(db, item)


def _sync_workspace_skill_draft(
    db: Session,
    storage: ManagedStorage,
    *,
    run: Run,
    user: User,
    written_path: str,
) -> dict[str, Any] | None:
    parts = PurePosixPath(written_path).parts
    if (
        len(parts) < 4
        or tuple(part.casefold() for part in parts[:2]) != SKILL_WORKSPACE_ROOT
    ):
        return None
    slug = parts[2]
    root = f"extensions/skills/{slug}"
    package: dict[str, str] = {}
    for item in _active_files(db, run):
        item_parts = PurePosixPath(item.logical_path).parts
        if (
            len(item_parts) < 4
            or tuple(part.casefold() for part in item_parts[:2])
            != SKILL_WORKSPACE_ROOT
            or item_parts[2].casefold() != slug.casefold()
        ):
            continue
        version = get_project_file_version(db, item)
        try:
            content = _decode_text(
                storage.read_bytes(
                    version.storage_key,
                    expected_sha256=version.content_hash,
                )
            )
        except ValueError:
            continue
        package[PurePosixPath(item.logical_path).relative_to(root).as_posix()] = content
    skill_md = next(
        (content for path, content in package.items() if path.casefold() == "skill.md"),
        None,
    )
    if skill_md is None:
        return None
    metadata = _skill_frontmatter(skill_md)
    extension, draft, changed = sync_workspace_skill(
        db,
        user=user,
        project_id=run.project_id,
        source_conversation_id=run.conversation_id,
        slug=slug,
        name=metadata.get("name") or slug,
        description=metadata.get("description", ""),
        package_files=package,
    )
    if changed:
        record_audit(
            db,
            action=(
                "extension_created_from_workspace"
                if draft.current_revision == 1
                else "extension_draft_synced_from_workspace"
            ),
            target_type="extension",
            target_id=extension.id,
            result="success",
            actor=user,
            metadata={
                "projectId": run.project_id,
                "conversationId": run.conversation_id,
                "draftRevision": draft.current_revision,
            },
        )
    return {
        "extensionId": extension.id,
        "draftId": draft.id,
        "slug": extension.slug,
        "name": extension.name,
        "revision": draft.current_revision,
        "digest": draft.current_digest,
        "changed": changed,
    }


def _create_workspace_skill(
    db: Session,
    storage: ManagedStorage,
    *,
    run: Run,
    user: User,
    arguments: dict[str, Any],
    max_upload_bytes: int,
) -> dict[str, Any]:
    slug = str(arguments.get("slug") or "").strip()
    name = str(arguments.get("name") or "").strip()
    description = str(arguments.get("description") or "").strip()
    raw_files = arguments.get("files")
    if not isinstance(raw_files, dict):
        raise ValueError("Skill package files는 object여야 합니다.")
    package_files = {
        str(path): str(content)
        for path, content in raw_files.items()
        if isinstance(path, str) and isinstance(content, str)
    }
    if len(package_files) != len(raw_files):
        raise ValueError("Skill package 경로와 내용은 문자열이어야 합니다.")

    extension, draft, changed = sync_workspace_skill(
        db,
        user=user,
        project_id=run.project_id,
        source_conversation_id=run.conversation_id,
        slug=slug,
        name=name,
        description=description,
        package_files=package_files,
    )
    package_root = f"extensions/skills/{extension.slug}"
    written_files: list[dict[str, Any]] = []
    current_files = _current_files(db, run.project_id)
    expected_paths: set[str] = set()
    for relative_path, content in sorted(draft.package_json.items()):
        logical_path = normalize_logical_path(f"{package_root}/{relative_path}")
        expected_paths.add(logical_path.casefold())
        encoded = content.encode("utf-8")
        existing = next(
            (
                item
                for item in current_files
                if item.logical_path.casefold() == logical_path.casefold()
            ),
            None,
        )
        if existing is None:
            item, version = create_project_file(
                db,
                user=user,
                project_id=run.project_id,
                logical_path=logical_path,
                original_filename=PurePosixPath(logical_path).name,
                content=encoded,
                change_reason="Agent create_skill",
                max_upload_bytes=max_upload_bytes,
                storage=storage,
            )
            current_files.append(item)
            action = "created"
        else:
            current_version = get_project_file_version(db, existing)
            if current_version.content_hash == _content_hash(encoded):
                item, version, action = existing, current_version, "unchanged"
            else:
                item, version = create_project_file_version(
                    db,
                    user=user,
                    project_id=run.project_id,
                    file_id=existing.id,
                    base_version=existing.current_version_number,
                    original_filename=PurePosixPath(logical_path).name,
                    content=encoded,
                    change_reason="Agent create_skill",
                    source_run_id=run.id,
                    max_upload_bytes=max_upload_bytes,
                    storage=storage,
                )
                action = "updated"
        written_files.append(
            {
                "path": item.logical_path,
                "action": action,
                "version": version.version_number,
                "contentHash": version.content_hash,
            }
        )

    removed_files: list[str] = []
    package_prefix = f"{package_root}/".casefold()
    for item in current_files:
        logical_key = item.logical_path.casefold()
        if logical_key.startswith(package_prefix) and logical_key not in expected_paths:
            soft_delete_project_file(
                db,
                user=user,
                project_id=run.project_id,
                file_id=item.id,
                expected_revision=item.revision,
            )
            removed_files.append(item.logical_path)

    record_audit(
        db,
        action=(
            "extension_created_from_workspace"
            if draft.current_revision == 1
            else "extension_draft_synced_from_workspace"
        ),
        target_type="extension",
        target_id=extension.id,
        result="success",
        actor=user,
        metadata={
            "projectId": run.project_id,
            "conversationId": run.conversation_id,
            "draftRevision": draft.current_revision,
            "packageRoot": package_root,
            "removedFiles": removed_files,
        },
    )
    return {
        "extensionId": extension.id,
        "draftId": draft.id,
        "slug": extension.slug,
        "name": extension.name,
        "revision": draft.current_revision,
        "digest": draft.current_digest,
        "changed": changed,
        "packageRoot": package_root,
        "files": written_files,
        "removedFiles": removed_files,
    }


def _current_files(db: Session, project_id: str) -> list[ProjectFile]:
    return list(
        db.scalars(
            select(ProjectFile)
            .where(
                ProjectFile.project_id == project_id,
                ProjectFile.deleted_at.is_(None),
            )
            .order_by(ProjectFile.logical_path)
        )
    )


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _skill_frontmatter(content: str) -> dict[str, str]:
    match = _SKILL_FRONTMATTER.match(content.replace("\r\n", "\n"))
    if match is None:
        return {}
    metadata: dict[str, str] = {}
    active_key: str | None = None
    for raw_line in match.group(1).splitlines():
        if raw_line[:1].isspace() and active_key:
            metadata[active_key] = f"{metadata[active_key]} {raw_line.strip()}".strip()
            continue
        key, separator, value = raw_line.partition(":")
        normalized_key = key.strip()
        if separator and normalized_key in {"name", "description"}:
            active_key = normalized_key
            cleaned = value.strip().strip("'\"")
            metadata[active_key] = "" if cleaned in {">", "|", ">-", "|-"} else cleaned
        else:
            active_key = None
    return metadata


def _require_file(files: list[ProjectFile], raw_path: Any) -> ProjectFile:
    path = normalize_logical_path(str(raw_path or ""))
    item = next(
        (
            candidate
            for candidate in files
            if candidate.logical_path.casefold() == path.casefold()
        ),
        None,
    )
    if item is None:
        raise ValueError(f"Project file not found: {path}")
    return item


def _glob_pattern(value: Any) -> str:
    pattern = str(value or "").strip().replace("\\", "/")
    if not pattern or pattern.startswith("/") or ".." in PurePosixPath(pattern).parts:
        raise ValueError("Glob pattern must stay within the Project workspace.")
    return pattern


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern) or (
        pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:])
    )


def _limit(value: Any) -> int:
    return min(MAX_RESULTS, max(1, int(value)))


def _limited_paths(paths: list[str], limit: int) -> dict[str, Any]:
    return {
        "paths": paths[:limit],
        "count": min(len(paths), limit),
        "truncated": len(paths) > limit,
    }


def _list_dir(files: list[ProjectFile], raw_path: str, limit: int) -> dict[str, Any]:
    directory = raw_path.strip().strip("/").replace("\\", "/")
    if directory:
        normalize_logical_path(f"{directory}/placeholder")
    prefix = f"{directory}/" if directory else ""
    children: dict[str, str] = {}
    for item in files:
        if not item.logical_path.startswith(prefix):
            continue
        remainder = item.logical_path[len(prefix) :]
        first, separator, _ = remainder.partition("/")
        children[first] = "directory" if separator else "file"
    entries = [{"name": name, "type": kind} for name, kind in sorted(children.items())]
    return {
        "path": directory,
        "entries": entries[:limit],
        "count": min(len(entries), limit),
        "truncated": len(entries) > limit,
    }


def _grep(
    db: Session,
    storage: ManagedStorage,
    run: Run,
    files: list[ProjectFile],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    query = str(arguments.get("query", ""))
    if not query:
        raise ValueError("query is required")
    prefix = str(arguments.get("path", "")).strip().strip("/").replace("\\", "/")
    if prefix:
        normalize_logical_path(prefix)
    pattern = _glob_pattern(arguments.get("glob", "**/*"))
    case_sensitive = bool(arguments.get("case_sensitive", False))
    use_regex = bool(arguments.get("regex", False))
    limit = _limit(arguments.get("limit", 100))
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        expression = re.compile(query if use_regex else re.escape(query), flags)
    except re.error as exc:
        raise ValueError(f"Invalid regular expression: {exc}") from exc
    matches: list[dict[str, Any]] = []
    for item in files:
        if (
            prefix
            and item.logical_path != prefix
            and not item.logical_path.startswith(f"{prefix}/")
        ):
            continue
        if not _matches(item.logical_path, pattern):
            continue
        version = _run_file_version(db, run, item)
        try:
            text = _decode_text(
                storage.read_bytes(
                    version.storage_key, expected_sha256=version.content_hash
                )
            )
        except ValueError:
            continue
        for line_number, line in enumerate(text[:MAX_GREP_FILE_CHARS].splitlines(), 1):
            if expression.search(line):
                matches.append(
                    {
                        "path": item.logical_path,
                        "line": line_number,
                        "text": line[:1000],
                    }
                )
                if len(matches) >= limit:
                    return {
                        "matches": matches,
                        "count": len(matches),
                        "truncated": True,
                    }
    return {"matches": matches, "count": len(matches), "truncated": False}


def _decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("The requested Project file is not UTF-8 text.") from exc


__all__ = [
    "ARTIFACT_WRITE_TOOL_SCHEMA",
    "WORKSPACE_TOOL_SCHEMAS",
    "execute_workspace_tool",
]
