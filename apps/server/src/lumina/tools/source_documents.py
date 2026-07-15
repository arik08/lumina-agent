from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..context import estimate_text_tokens
from ..models import (
    Artifact,
    ArtifactVersion,
    Attachment,
    Message,
    ProjectFile,
    ProjectFileVersion,
    Run,
)
from ..storage import ManagedStorage


SOURCE_DOCUMENT_PREVIEW_CHARS = 1_200
SOURCE_DOCUMENT_CHUNK_LINES = 160
SOURCE_DOCUMENT_CHUNK_OVERLAP_LINES = 20
SOURCE_DOCUMENT_MAX_SEARCH_MATCHES = 20
SOURCE_DOCUMENT_MAX_READ_LINES = 2_000
SOURCE_DOCUMENT_MAX_READ_CHARS = 100_000
SOURCE_DOCUMENT_FALLBACK_THRESHOLD_TOKENS = 20_000
SOURCE_DOCUMENT_MAX_THRESHOLD_TOKENS = 80_000
_SOURCE_DOCUMENT_CONTEXT_FRACTION = 0.20
_DOCUMENT_ID_SEPARATOR = ":"
_QUERY_TOKEN_RE = re.compile(r"\S+")


SOURCE_DOCUMENT_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "type": "function",
        "function": {
            "name": "search_source_document",
            "description": (
                "Search a large source document referenced by the current Run. "
                "Use this before drawing source-backed conclusions from a document manifest."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "minLength": 1, "maxLength": 300},
                    "query": {"type": "string", "minLength": 1, "maxLength": 1_000},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": SOURCE_DOCUMENT_MAX_SEARCH_MATCHES,
                        "default": 8,
                    },
                },
                "required": ["document_id", "query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_source_document",
            "description": (
                "Read exact original line ranges from a large source document referenced "
                "by the current Run. Use it after search_source_document."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "minLength": 1, "maxLength": 300},
                    "start_line": {"type": "integer", "minimum": 1, "default": 1},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": SOURCE_DOCUMENT_MAX_READ_LINES,
                        "default": 200,
                    },
                },
                "required": ["document_id"],
                "additionalProperties": False,
            },
        },
    },
)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    document_id: str
    name: str
    source_kind: str
    content: str


def source_document_threshold_tokens(context_window: int | None) -> int:
    if context_window is None or context_window <= 0:
        return SOURCE_DOCUMENT_FALLBACK_THRESHOLD_TOKENS
    return min(
        SOURCE_DOCUMENT_MAX_THRESHOLD_TOKENS,
        max(4_000, int(context_window * _SOURCE_DOCUMENT_CONTEXT_FRACTION)),
    )


def should_externalize_source_document(
    content: str,
    *,
    context_window: int | None,
    remaining_inline_chars: int,
) -> bool:
    return len(content) > max(0, remaining_inline_chars) or estimate_text_tokens(
        content
    ) >= source_document_threshold_tokens(context_window)


def attachment_source_document_id(attachment: Attachment) -> str:
    digest = str(attachment.metadata_json.get("extractedContentHash", ""))
    return _document_id("attachment", attachment.id, digest)


def project_file_source_document_id(file_id: str, digest: str) -> str:
    return _document_id("project-file", file_id, digest)


def artifact_source_document_id(artifact_id: str, digest: str) -> str:
    return _document_id("artifact", artifact_id, digest)


def message_source_document_id(message_id: str, content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return _document_id("message", message_id, digest)


def source_document_user_request(text: str) -> str:
    parts = [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]
    if len(parts) >= 2:
        return parts[-1][:1_200]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-3:])[:1_200]


def build_source_document_manifest(
    *,
    document_id: str,
    name: str,
    source_kind: str,
    content: str,
    source_truncated: bool = False,
    user_request: str | None = None,
) -> str:
    metadata = {
        "documentId": document_id,
        "name": name,
        "sourceKind": source_kind,
        "lineCount": len(content.splitlines()),
        "charCount": len(content),
        "estimatedTokens": estimate_text_tokens(content),
        "sourceTruncatedDuringExtraction": source_truncated,
    }
    request_section = (
        f"\nUser request retained outside the stored source:\n{user_request.strip()}\n"
        if user_request and user_request.strip()
        else ""
    )
    return (
        "<source-document-manifest>\n"
        + json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        + request_section
        + "\nDocument sample only; do not rely on it for substantive conclusions:\n"
        + _sample(content)
        + "\nRequired retrieval workflow:\n"
        + f'- Search with search_source_document(document_id="{document_id}", query=...).\n'
        + f'- Verify exact lines with read_source_document(document_id="{document_id}", '
        "start_line=..., limit=...).\n"
        + "- Never request or paste the entire document into one model turn.\n"
        + "</source-document-manifest>"
    )


def execute_source_document_tool(
    db: Session,
    file_storage: ManagedStorage,
    artifact_storage: ManagedStorage,
    *,
    run: Run,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    document_id = str(arguments.get("document_id", "")).strip()
    document = _resolve_source_document(
        db,
        file_storage,
        artifact_storage,
        run=run,
        document_id=document_id,
    )
    if name == "search_source_document":
        return _search_document(document, arguments)
    if name == "read_source_document":
        return _read_document(document, arguments)
    raise ValueError(f"Unknown source document tool: {name}")


def _resolve_source_document(
    db: Session,
    file_storage: ManagedStorage,
    artifact_storage: ManagedStorage,
    *,
    run: Run,
    document_id: str,
) -> SourceDocument:
    parts = document_id.split(_DOCUMENT_ID_SEPARATOR)
    if len(parts) != 3 or not all(parts):
        raise ValueError("Source document ID is invalid or unavailable for this Run.")
    source_kind, source_id, digest = parts
    if source_kind == "message":
        message = db.get(Message, source_id)
        if (
            message is None
            or message.conversation_id != run.conversation_id
            or message.role != "user"
            or hashlib.sha256(message.canonical_text.encode("utf-8")).hexdigest()
            != digest
        ):
            raise ValueError("Source document is unavailable for this Run.")
        return SourceDocument(
            document_id=document_id,
            name="Pasted user document",
            source_kind=source_kind,
            content=message.canonical_text,
        )
    if source_kind == "attachment":
        attachment = db.get(Attachment, source_id)
        if (
            attachment is None
            or attachment.project_id != run.project_id
            or attachment.conversation_id != run.conversation_id
            or attachment.status != "ready"
            or attachment.extraction_status != "completed"
            or attachment.metadata_json.get("extractedContentHash") != digest
        ):
            raise ValueError("Source document is unavailable for this Run.")
        key = attachment.metadata_json.get("extractedStorageKey")
        if not isinstance(key, str):
            raise ValueError("Source document extraction is unavailable.")
        content = file_storage.read_bytes(key, expected_sha256=digest).decode(
            "utf-8", errors="replace"
        )
        return SourceDocument(
            document_id=document_id,
            name=attachment.original_filename,
            source_kind=source_kind,
            content=content,
        )
    if source_kind == "project-file":
        project_file = db.get(ProjectFile, source_id)
        if project_file is None or project_file.project_id != run.project_id:
            raise ValueError("Source document is unavailable for this Run.")
        version = db.scalar(
            select(ProjectFileVersion)
            .where(
                ProjectFileVersion.project_file_id == project_file.id,
                ProjectFileVersion.content_hash == digest,
            )
            .order_by(ProjectFileVersion.version_number.desc())
            .limit(1)
        )
        if version is None:
            raise ValueError("Source document version is unavailable for this Run.")
        content = _project_file_version_content(file_storage, version)
        return SourceDocument(
            document_id=document_id,
            name=project_file.logical_path,
            source_kind=source_kind,
            content=content,
        )
    if source_kind == "artifact":
        artifact = db.get(Artifact, source_id)
        if artifact is None or artifact.project_id != run.project_id:
            raise ValueError("Source document is unavailable for this Run.")
        version = db.scalar(
            select(ArtifactVersion)
            .where(
                ArtifactVersion.artifact_id == artifact.id,
                ArtifactVersion.content_hash == digest,
            )
            .order_by(ArtifactVersion.version_number.desc())
            .limit(1)
        )
        if version is None:
            raise ValueError("Source document version is unavailable for this Run.")
        content = artifact_storage.read_bytes(
            version.storage_key, expected_sha256=version.content_hash
        ).decode("utf-8", errors="replace")
        return SourceDocument(
            document_id=document_id,
            name=artifact.display_name,
            source_kind=source_kind,
            content=content,
        )
    raise ValueError("Source document type is unavailable for this Run.")


def _project_file_version_content(
    storage: ManagedStorage, version: ProjectFileVersion
) -> str:
    key = version.metadata_json.get("extractedStorageKey")
    digest = version.metadata_json.get("extractedContentHash")
    if isinstance(key, str) and isinstance(digest, str):
        raw = storage.read_bytes(key, expected_sha256=digest)
    elif version.mime_type.startswith("text/"):
        raw = storage.read_bytes(
            version.storage_key, expected_sha256=version.content_hash
        )
    else:
        raise ValueError("Source document text extraction is unavailable.")
    return raw.decode("utf-8", errors="replace")


def _search_document(
    document: SourceDocument, arguments: dict[str, Any]
) -> dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")
    limit = _bounded_int(
        arguments.get("limit", 8), 1, SOURCE_DOCUMENT_MAX_SEARCH_MATCHES
    )
    lines = document.content.splitlines()
    matches: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(_line_chunks(len(lines)), start=1):
        chunk_lines = lines[start - 1 : end]
        chunk = "\n".join(chunk_lines)
        score = _score(chunk, query)
        if score <= 0:
            continue
        matches.append(
            {
                "chunk": index,
                "startLine": start,
                "endLine": end,
                "score": score,
                "snippet": _matching_snippet(chunk_lines, query),
            }
        )
    matches.sort(key=lambda item: (-int(item["score"]), int(item["startLine"])))
    return {
        "documentId": document.document_id,
        "name": document.name,
        "query": query,
        "matches": matches[:limit],
        "matchCount": min(len(matches), limit),
        "truncated": len(matches) > limit,
        "untrustedExternalContent": True,
    }


def _read_document(
    document: SourceDocument, arguments: dict[str, Any]
) -> dict[str, Any]:
    start_line = max(1, int(arguments.get("start_line", 1)))
    limit = _bounded_int(arguments.get("limit", 200), 1, SOURCE_DOCUMENT_MAX_READ_LINES)
    lines = document.content.splitlines()
    selected: list[str] = []
    next_line = start_line
    rendered_chars = 0
    for line_number, line in enumerate(
        lines[start_line - 1 : start_line - 1 + limit], start=start_line
    ):
        rendered = f"{line_number}|{line}"
        projected = len(rendered) + (1 if selected else 0)
        if selected and rendered_chars + projected > SOURCE_DOCUMENT_MAX_READ_CHARS:
            break
        selected.append(rendered[:SOURCE_DOCUMENT_MAX_READ_CHARS])
        rendered_chars += projected
        next_line = line_number + 1
        if len(rendered) >= SOURCE_DOCUMENT_MAX_READ_CHARS:
            break
    has_more = next_line <= len(lines)
    return {
        "documentId": document.document_id,
        "name": document.name,
        "startLine": start_line,
        "lineCount": len(lines),
        "nextStartLine": next_line if has_more else None,
        "truncated": has_more,
        "content": "\n".join(selected),
        "untrustedExternalContent": True,
    }


def _document_id(source_kind: str, source_id: str, digest: str) -> str:
    if not source_id or not digest or _DOCUMENT_ID_SEPARATOR in source_id + digest:
        raise ValueError("Cannot build a source document ID from incomplete metadata.")
    return _DOCUMENT_ID_SEPARATOR.join((source_kind, source_id, digest))


def _sample(content: str) -> str:
    clean = content.strip()
    if len(clean) <= SOURCE_DOCUMENT_PREVIEW_CHARS:
        return clean
    part = SOURCE_DOCUMENT_PREVIEW_CHARS // 3
    midpoint = max(0, len(clean) // 2 - part // 2)
    return "\n...\n".join(
        (
            clean[:part].rstrip(),
            clean[midpoint : midpoint + part].strip(),
            clean[-part:].lstrip(),
        )
    )


def _line_chunks(line_count: int) -> list[tuple[int, int]]:
    if line_count <= 0:
        return []
    chunks: list[tuple[int, int]] = []
    start = 1
    step = SOURCE_DOCUMENT_CHUNK_LINES - SOURCE_DOCUMENT_CHUNK_OVERLAP_LINES
    while start <= line_count:
        end = min(line_count, start + SOURCE_DOCUMENT_CHUNK_LINES - 1)
        chunks.append((start, end))
        if end >= line_count:
            break
        start += step
    return chunks


def _score(text: str, query: str) -> int:
    haystack = text.casefold()
    needle = query.casefold()
    score = 100 if needle in haystack else 0
    score += sum(10 for token in _QUERY_TOKEN_RE.findall(needle) if token in haystack)
    return score


def _matching_snippet(lines: list[str], query: str) -> str:
    needle = query.casefold()
    tokens = _QUERY_TOKEN_RE.findall(needle)
    candidate = next(
        (line for line in lines if needle in line.casefold()),
        next(
            (
                line
                for line in lines
                if any(token in line.casefold() for token in tokens)
            ),
            next((line for line in lines if line.strip()), ""),
        ),
    )
    clean = " ".join(candidate.split())
    return clean if len(clean) <= 220 else clean[:217].rstrip() + "..."


def _bounded_int(value: Any, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("Tool pagination values must be integers.")
    return min(maximum, max(minimum, value))


__all__ = [
    "SOURCE_DOCUMENT_TOOL_SCHEMAS",
    "artifact_source_document_id",
    "attachment_source_document_id",
    "build_source_document_manifest",
    "execute_source_document_tool",
    "message_source_document_id",
    "project_file_source_document_id",
    "should_externalize_source_document",
    "source_document_user_request",
    "source_document_threshold_tokens",
]
