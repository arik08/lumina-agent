from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ProjectFile, Run, User
from ..project_files.service import (
    create_project_file,
    create_project_file_version,
    get_project_file_version,
    normalize_logical_path,
)
from ..storage import ManagedStorage


MAX_RESULTS = 200
MAX_READ_LINES = 2_000
MAX_READ_CHARS = 100_000
MAX_GREP_FILE_CHARS = 1_000_000


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
            "name": "write_file",
            "description": "Create or replace a UTF-8 text file in the current Project workspace. Replacing a file creates a new immutable version.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
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
    files = _active_files(db, run.project_id)
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
        version = get_project_file_version(db, item)
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
        return _grep(db, storage, files, arguments)
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
        return {
            "projectFileId": item.id,
            "path": item.logical_path,
            "action": action,
            "version": version.version_number,
            "mimeType": version.mime_type,
            "contentHash": version.content_hash,
            "sizeBytes": version.size_bytes,
        }
    raise ValueError(f"Unknown workspace tool: {name}")


def _active_files(db: Session, project_id: str) -> list[ProjectFile]:
    return list(
        db.scalars(
            select(ProjectFile)
            .where(
                ProjectFile.project_id == project_id, ProjectFile.deleted_at.is_(None)
            )
            .order_by(ProjectFile.logical_path)
        )
    )


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
        version = get_project_file_version(db, item)
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


__all__ = ["WORKSPACE_TOOL_SCHEMAS", "execute_workspace_tool"]
