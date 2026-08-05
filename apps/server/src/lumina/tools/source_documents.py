from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from threading import RLock
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..attachments.extraction import extract_attachment_text

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
SOURCE_DOCUMENT_MAX_OUTLINE_NODES = 80
SOURCE_DOCUMENT_MAX_READ_LINES = 2_000
SOURCE_DOCUMENT_MAX_READ_CHARS = 100_000
SOURCE_DOCUMENT_FALLBACK_THRESHOLD_TOKENS = 20_000
SOURCE_DOCUMENT_MAX_THRESHOLD_TOKENS = 80_000
_SOURCE_DOCUMENT_CONTEXT_FRACTION = 0.20
_DOCUMENT_ID_SEPARATOR = ":"
_QUERY_TOKEN_RE = re.compile(r"\S+")
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_KOREAN_SECTION_HEADING_RE = re.compile(
    r"^\s*(제\s*\d+\s*(편|장|절|관|조)(?:의\s*\d+)?)"
    r"\s*(?:[\[(（](.+?)[\])）]|(.+?))?\s*$"
)
_DECIMAL_HEADING_RE = re.compile(
    r"^\s*((?:[1-9]\d*)(?:\.(?:[1-9]\d*)){1,4})[.)]?\s+(.+?)\s*$"
)
_BROAD_DOCUMENT_REQUEST_RE = re.compile(
    r"(전체|전반|빠짐없이|모든\s*(?:장|절|조항|규정)|충돌|상충|예외|부칙|"
    r"책임|절차|누락|cross[- ]?section|conflict|exception|comprehensive|"
    r"entire\s+document|all\s+sections)",
    re.IGNORECASE,
)
_EXACT_DOCUMENT_REQUEST_RE = re.compile(
    r"(제\s*\d+\s*조|제\s*\d+\s*(?:장|절)|\b(?:article|section)\s+\d+|"
    r"정확한\s*(?:문구|표현)|그\s*문구|찾아(?:줘|주세요)|show\s+me|find\s+)",
    re.IGNORECASE,
)
_SOURCE_DOCUMENT_CACHE_MAX_CHARACTERS = 20_000_000
_source_document_cache: OrderedDict[str, "SourceDocument"] = OrderedDict()
_source_document_cache_characters = 0
_source_document_cache_lock = RLock()


SOURCE_DOCUMENT_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "type": "function",
        "function": {
            "name": "explore_source_document",
            "description": (
                "Explore the section tree of a structured source document referenced by the "
                "current Run. Use it before broad, cross-section, conflict, exception, or "
                "whole-document analysis. Start without parent_node_id, then request direct "
                "children as needed. The outline is navigation metadata, not evidence: verify "
                "every substantive conclusion with search_source_document and "
                "read_source_document. For exhaustive analysis, traverse every relevant "
                "top-level branch."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "minLength": 1, "maxLength": 300},
                    "parent_node_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 80,
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": SOURCE_DOCUMENT_MAX_OUTLINE_NODES,
                        "default": 40,
                    },
                },
                "required": ["document_id"],
                "additionalProperties": False,
            },
        },
    },
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
    lines: tuple[str, ...]
    character_count: int


@dataclass(frozen=True, slots=True)
class SourceDocumentSection:
    node_id: str
    title: str
    level: int
    start_line: int
    end_line: int
    parent_node_id: str | None


def _cached_source_document(
    document_id: str,
    *,
    name: str,
    source_kind: str,
    content_loader: Callable[[], str],
) -> SourceDocument:
    global _source_document_cache_characters
    with _source_document_cache_lock:
        cached = _source_document_cache.get(document_id)
        if cached is not None:
            _source_document_cache.move_to_end(document_id)
            return cached
    content = str(content_loader())
    document = SourceDocument(
        document_id=document_id,
        name=name,
        source_kind=source_kind,
        lines=tuple(content.splitlines()),
        character_count=len(content),
    )
    if document.character_count > _SOURCE_DOCUMENT_CACHE_MAX_CHARACTERS:
        return document
    with _source_document_cache_lock:
        cached = _source_document_cache.get(document_id)
        if cached is not None:
            _source_document_cache.move_to_end(document_id)
            return cached
        _source_document_cache[document_id] = document
        _source_document_cache.move_to_end(document_id)
        _source_document_cache_characters += document.character_count
        while (
            _source_document_cache
            and _source_document_cache_characters
            > _SOURCE_DOCUMENT_CACHE_MAX_CHARACTERS
        ):
            _, removed = _source_document_cache.popitem(last=False)
            _source_document_cache_characters -= removed.character_count
    return document


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
    navigation = _document_navigation_profile(
        content,
        user_request=user_request,
        context_pressure=True,
        extraction_reliable=not source_truncated,
    )
    metadata = {
        "documentId": document_id,
        "name": name,
        "sourceKind": source_kind,
        "lineCount": len(content.splitlines()),
        "charCount": len(content),
        "estimatedTokens": estimate_text_tokens(content),
        "sourceTruncatedDuringExtraction": source_truncated,
        "navigation": navigation,
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
        + (
            f'- Explore structure with explore_source_document(document_id="{document_id}") '
            "before broad or cross-section analysis.\n"
            if navigation["strategy"] == "explore_then_search_then_read"
            else ""
        )
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
    if name == "explore_source_document":
        return _explore_document(document, arguments)
    if name == "search_source_document":
        return _search_document(document, arguments)
    if name == "read_source_document":
        return _read_document(document, arguments)
    raise ValueError(f"Unknown source document tool: {name}")


def _explore_document(
    document: SourceDocument, arguments: dict[str, Any]
) -> dict[str, Any]:
    sections = _document_sections(document.lines)
    profile = _document_navigation_profile(
        "\n".join(document.lines),
        section_count=len(sections),
    )
    raw_parent = arguments.get("parent_node_id")
    parent_node_id = str(raw_parent).strip() if raw_parent is not None else None
    if parent_node_id and not any(
        section.node_id == parent_node_id for section in sections
    ):
        raise ValueError("Source document section node is unavailable.")
    limit = _bounded_int(
        arguments.get("limit", 40), 1, SOURCE_DOCUMENT_MAX_OUTLINE_NODES
    )
    children_by_parent: dict[str | None, int] = {}
    for section in sections:
        children_by_parent[section.parent_node_id] = (
            children_by_parent.get(section.parent_node_id, 0) + 1
        )
    candidates = [
        section
        for section in sections
        if section.parent_node_id == parent_node_id
    ]
    selected = candidates[:limit]
    return {
        "documentId": document.document_id,
        "name": document.name,
        "available": bool(sections),
        "strategy": profile["strategy"],
        "reason": profile["reason"],
        "parentNodeId": parent_node_id,
        "nodes": [
            {
                "nodeId": section.node_id,
                "title": section.title,
                "level": section.level,
                "startLine": section.start_line,
                "endLine": section.end_line,
                "childCount": children_by_parent.get(section.node_id, 0),
            }
            for section in selected
        ],
        "nodeCount": len(sections),
        "returned": len(selected),
        "truncated": len(candidates) > len(selected),
        "instruction": (
            "Use this outline only for navigation. Search and read exact source lines before "
            "drawing conclusions."
        ),
        "untrustedExternalContent": True,
    }


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
        return _cached_source_document(
            document_id,
            name="Pasted user document",
            source_kind=source_kind,
            content_loader=lambda: message.canonical_text,
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
        return _cached_source_document(
            document_id,
            name=attachment.original_filename,
            source_kind=source_kind,
            content_loader=lambda: file_storage.read_bytes(
                key, expected_sha256=digest
            ).decode("utf-8", errors="replace"),
        )
    if source_kind == "project-file":
        project_file = db.get(ProjectFile, source_id)
        if project_file is None or project_file.project_id != run.project_id:
            raise ValueError("Source document is unavailable for this Run.")
        project_file_version = db.scalar(
            select(ProjectFileVersion)
            .where(
                ProjectFileVersion.project_file_id == project_file.id,
                ProjectFileVersion.content_hash == digest,
            )
            .order_by(ProjectFileVersion.version_number.desc())
            .limit(1)
        )
        if project_file_version is None:
            raise ValueError("Source document version is unavailable for this Run.")
        return _cached_source_document(
            document_id,
            name=project_file.logical_path,
            source_kind=source_kind,
            content_loader=lambda: _project_file_version_content(
                file_storage, project_file_version
            ),
        )
    if source_kind == "artifact":
        artifact = db.get(Artifact, source_id)
        if artifact is None or artifact.project_id != run.project_id:
            raise ValueError("Source document is unavailable for this Run.")
        artifact_version = db.scalar(
            select(ArtifactVersion)
            .where(
                ArtifactVersion.artifact_id == artifact.id,
                ArtifactVersion.content_hash == digest,
            )
            .order_by(ArtifactVersion.version_number.desc())
            .limit(1)
        )
        if artifact_version is None:
            raise ValueError("Source document version is unavailable for this Run.")
        return _cached_source_document(
            document_id,
            name=artifact.display_name,
            source_kind=source_kind,
            content_loader=lambda: _artifact_version_content(
                artifact_storage, artifact, artifact_version
            ),
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


def _artifact_version_content(
    storage: ManagedStorage, artifact: Artifact, version: ArtifactVersion
) -> str:
    raw = storage.read_bytes(version.storage_key, expected_sha256=version.content_hash)
    extracted = extract_attachment_text(
        filename=artifact.display_name,
        mime_type=artifact.mime_type,
        content=raw,
    )
    if extracted.status != "completed":
        raise ValueError("Artifact text extraction is unavailable.")
    return extracted.text


def _search_document(
    document: SourceDocument, arguments: dict[str, Any]
) -> dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")
    limit = _bounded_int(
        arguments.get("limit", 8), 1, SOURCE_DOCUMENT_MAX_SEARCH_MATCHES
    )
    lines = document.lines
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
    lines = document.lines
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


def _document_navigation_profile(
    content: str,
    *,
    user_request: str | None = None,
    section_count: int | None = None,
    context_pressure: bool | None = None,
    extraction_reliable: bool = True,
) -> dict[str, Any]:
    lines = tuple(content.splitlines())
    sections = (
        _document_sections(lines)
        if section_count is None
        else ()
    )
    detected_section_count = (
        len(sections) if section_count is None else section_count
    )
    estimated_tokens = estimate_text_tokens(content)
    structured = detected_section_count >= 3
    request = (user_request or "").strip()
    broad_request = bool(_BROAD_DOCUMENT_REQUEST_RE.search(request))
    exact_request = bool(_EXACT_DOCUMENT_REQUEST_RE.search(request))
    has_context_pressure = (
        estimated_tokens >= SOURCE_DOCUMENT_FALLBACK_THRESHOLD_TOKENS
        if context_pressure is None
        else context_pressure
    )
    should_explore = structured and (
        broad_request or (has_context_pressure and not exact_request)
    )
    if not extraction_reliable:
        strategy = "search_then_read"
        reason = "source_extraction_incomplete"
    elif should_explore:
        strategy = "explore_then_search_then_read"
        reason = (
            "broad_structured_request"
            if broad_request
            else "large_structured_document"
        )
    elif not structured:
        strategy = "search_then_read"
        reason = "no_reliable_section_structure"
    elif exact_request:
        strategy = "search_then_read"
        reason = "exact_lookup_request"
    else:
        strategy = "search_then_read"
        reason = "structure_not_needed_for_current_request"
    return {
        "strategy": strategy,
        "reason": reason,
        "structured": structured,
        "sectionCount": detected_section_count,
        "estimatedTokens": estimated_tokens,
    }


def _document_sections(lines: tuple[str, ...]) -> tuple[SourceDocumentSection, ...]:
    headings: list[tuple[int, int, str]] = []
    for line_number, line in enumerate(lines, start=1):
        candidate = _section_heading(line)
        if candidate is None:
            continue
        level, title = candidate
        headings.append((line_number, level, title))
        if len(headings) > 1_000:
            return ()
    if len(headings) < 3 or len(headings) > max(20, len(lines) // 5):
        return ()

    parents: list[str | None] = []
    stack: list[tuple[int, str]] = []
    for line_number, level, _title in headings:
        while stack and stack[-1][0] >= level:
            stack.pop()
        parents.append(stack[-1][1] if stack else None)
        node_id = f"section:{line_number}"
        stack.append((level, node_id))

    sections: list[SourceDocumentSection] = []
    for index, ((line_number, level, title), parent_node_id) in enumerate(
        zip(headings, parents, strict=True)
    ):
        end_line = len(lines)
        for next_line, next_level, _next_title in headings[index + 1 :]:
            if next_level <= level:
                end_line = next_line - 1
                break
        sections.append(
            SourceDocumentSection(
                node_id=f"section:{line_number}",
                title=title,
                level=level,
                start_line=line_number,
                end_line=end_line,
                parent_node_id=parent_node_id,
            )
        )
    return tuple(sections)


def _section_heading(line: str) -> tuple[int, str] | None:
    stripped = line.strip()
    if not stripped or len(stripped) > 180:
        return None
    markdown = _MARKDOWN_HEADING_RE.match(stripped)
    if markdown:
        return len(markdown.group(1)), markdown.group(2).strip()
    korean = _KOREAN_SECTION_HEADING_RE.match(stripped)
    if korean:
        levels = {"편": 1, "장": 2, "절": 3, "관": 4, "조": 5}
        return levels[korean.group(2)], stripped
    decimal = _DECIMAL_HEADING_RE.match(stripped)
    if decimal:
        title = decimal.group(2).strip()
        if title.endswith((".", "!", "?", "。")):
            return None
        return len(decimal.group(1).split(".")), stripped
    return None


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


def _matching_snippet(lines: Sequence[str], query: str) -> str:
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
