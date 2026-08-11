"""Local SQLite GraphRAG store for organization Markdown documents."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from array import array
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml


DEFAULT_DIMENSIONS = 384
DEFAULT_TARGET_CHARS = 1600
DEFAULT_HARD_LIMIT_CHARS = 2400
SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".csv", ".json"}

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    line: int
    node_id: str
    parent_node_id: str | None


@dataclass(frozen=True)
class Block:
    kind: str
    text: str
    line_start: int
    line_end: int
    heading_stack: tuple[Heading, ...]


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    chunk_node_id: str
    section_node_id: str
    document_id: str
    document_name: str
    source_path: str
    heading_path: tuple[str, ...]
    org_path: tuple[str, ...]
    section_title: str
    content_kind: str
    line_start: int
    line_end: int
    text: str
    embedding: array


def default_base_dir() -> Path:
    return Path(__file__).resolve().parent


def default_documents_dir() -> Path:
    return default_base_dir() / "documents"


def default_db_path() -> Path:
    return default_base_dir() / "data" / "vector_graph.sqlite"


def init_db(db_path: str | Path) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                document_name TEXT NOT NULL,
                source_path TEXT NOT NULL UNIQUE,
                sha256 TEXT NOT NULL,
                mtime REAL NOT NULL,
                line_count INTEGER NOT NULL,
                indexed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                node_type TEXT NOT NULL,
                name TEXT NOT NULL,
                heading_path TEXT NOT NULL,
                org_path TEXT NOT NULL,
                line_start INTEGER NOT NULL,
                line_end INTEGER NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(document_id)
            );
            CREATE TABLE IF NOT EXISTS edges (
                edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                source_node_id TEXT NOT NULL,
                target_node_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                UNIQUE(document_id, source_node_id, target_node_id, edge_type)
            );
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                chunk_node_id TEXT NOT NULL,
                section_node_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                document_name TEXT NOT NULL,
                source_path TEXT NOT NULL,
                heading_path TEXT NOT NULL,
                org_path TEXT NOT NULL,
                section_title TEXT NOT NULL,
                content_kind TEXT NOT NULL,
                line_start INTEGER NOT NULL,
                line_end INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding BLOB NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(document_id)
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_document_type ON nodes(document_id, node_type);
            CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_node_id, edge_type);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_node_id, edge_type);
            CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_doc_name ON chunks(document_name);
            CREATE INDEX IF NOT EXISTS idx_chunks_section ON chunks(section_node_id);
            """
        )


def index_directory(
    documents_dir: str | Path | None = None,
    db_path: str | Path | None = None,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    hard_limit_chars: int = DEFAULT_HARD_LIMIT_CHARS,
) -> dict[str, Any]:
    docs_dir = Path(documents_dir or default_documents_dir())
    database = Path(db_path or default_db_path())
    docs_dir.mkdir(parents=True, exist_ok=True)
    init_db(database)

    indexed: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    files = sorted(
        path
        for path in docs_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    with sqlite3.connect(database) as db:
        for path in files:
            rel_path = _relative_source_path(path, docs_dir)
            seen_paths.add(rel_path)
            raw = path.read_text(encoding="utf-8", errors="replace")
            sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            mtime = path.stat().st_mtime
            current = db.execute(
                "SELECT sha256, mtime FROM documents WHERE source_path = ?",
                (rel_path,),
            ).fetchone()
            if current and current[0] == sha and float(current[1]) == float(mtime):
                indexed.append({"source_path": rel_path, "status": "unchanged"})
                continue
            result = index_markdown_file(
                db,
                path,
                docs_dir,
                text=raw,
                sha256=sha,
                mtime=mtime,
                target_chars=target_chars,
                hard_limit_chars=hard_limit_chars,
            )
            indexed.append(result)

        existing_paths = {
            row[0]
            for row in db.execute("SELECT source_path FROM documents").fetchall()
        }
        removed = sorted(existing_paths - seen_paths)
        for source_path in removed:
            document_id = db.execute(
                "SELECT document_id FROM documents WHERE source_path = ?",
                (source_path,),
            ).fetchone()[0]
            _delete_document(db, document_id)
        db.commit()

    return {
        "documents_dir": str(docs_dir),
        "db_path": str(database),
        "indexed": indexed,
        "removed": removed,
        **store_status(database),
    }


def index_markdown_file(
    db: sqlite3.Connection,
    path: Path,
    documents_dir: Path,
    *,
    text: str,
    sha256: str,
    mtime: float,
    target_chars: int,
    hard_limit_chars: int,
) -> dict[str, Any]:
    rel_path = _relative_source_path(path, documents_dir)
    document_id = _document_id(rel_path)
    metadata, content_lines = _split_frontmatter(text.splitlines())
    document_name = _document_name(path, metadata, content_lines)
    line_count = len(text.splitlines())
    indexed_at = datetime.now(timezone.utc).isoformat()

    _delete_document(db, document_id)
    db.execute(
        """
        INSERT INTO documents
            (document_id, document_name, source_path, sha256, mtime, line_count, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (document_id, document_name, rel_path, sha256, mtime, line_count, indexed_at),
    )

    document_node_id = f"doc:{document_id}"
    db.execute(
        """
        INSERT INTO nodes
            (node_id, document_id, node_type, name, heading_path, org_path, line_start, line_end)
        VALUES (?, ?, 'document', ?, ?, ?, 1, ?)
        """,
        (
            document_node_id,
            document_id,
            document_name,
            _json_list([document_name]),
            _json_list([]),
            max(1, line_count),
        ),
    )

    headings, blocks = parse_markdown_blocks(text, document_id)
    _insert_heading_graph(db, document_id, document_node_id, headings, line_count, document_name)
    chunks = build_chunks(
        blocks,
        document_id=document_id,
        document_name=document_name,
        source_path=rel_path,
        target_chars=target_chars,
        hard_limit_chars=hard_limit_chars,
    )
    for chunk in chunks:
        _insert_chunk(db, chunk)

    return {
        "source_path": rel_path,
        "document_id": document_id,
        "document_name": document_name,
        "status": "indexed",
        "line_count": line_count,
        "heading_count": len(headings),
        "chunk_count": len(chunks),
    }


def parse_markdown_blocks(text: str, document_id: str) -> tuple[list[Heading], list[Block]]:
    lines = text.splitlines()
    headings: list[Heading] = []
    blocks: list[Block] = []
    stack: list[Heading] = []
    pending: list[tuple[int, str]] = []
    frontmatter_end = _frontmatter_end_line(lines)

    def flush_pending() -> None:
        nonlocal pending
        if not pending:
            return
        blocks.extend(_pending_to_blocks(pending, tuple(stack)))
        pending = []

    for index, line in enumerate(lines, start=1):
        if frontmatter_end and index <= frontmatter_end:
            continue
        match = HEADING_RE.match(line.strip())
        if match:
            flush_pending()
            level = len(match.group(1))
            title = _clean_heading_title(match.group(2))
            stack = [heading for heading in stack if heading.level < level]
            parent_node_id = stack[-1].node_id if stack else None
            node_id = f"heading:{document_id}:{len(headings) + 1}"
            heading = Heading(level, title, index, node_id, parent_node_id)
            headings.append(heading)
            stack.append(heading)
            continue
        pending.append((index, line))
    flush_pending()
    return headings, blocks


def build_chunks(
    blocks: list[Block],
    *,
    document_id: str,
    document_name: str,
    source_path: str,
    target_chars: int,
    hard_limit_chars: int,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    current_blocks: list[Block] = []
    current_len = 0

    def flush_current() -> None:
        nonlocal current_blocks, current_len
        if not current_blocks:
            return
        chunks.append(
            _chunk_from_blocks(
                current_blocks,
                index=len(chunks) + 1,
                document_id=document_id,
                document_name=document_name,
                source_path=source_path,
            )
        )
        current_blocks = []
        current_len = 0

    for block in blocks:
        for part in _split_large_block(block, hard_limit_chars):
            part_len = len(part.text)
            same_section = (
                not current_blocks
                or current_blocks[-1].heading_stack == part.heading_stack
            )
            if (
                current_blocks
                and (not same_section or current_len + part_len > target_chars)
            ):
                flush_current()
            current_blocks.append(part)
            current_len += part_len
            if current_len >= hard_limit_chars:
                flush_current()
    flush_current()
    return chunks


def retrieve_context(
    query: str,
    *,
    db_path: str | Path | None = None,
    document_name: str | None = None,
    org_unit: str | None = None,
    mode: str = "hybrid",
    limit: int = 5,
) -> dict[str, Any]:
    database = Path(db_path or default_db_path())
    if not database.exists():
        return _not_indexed_response(database)
    clean_query = " ".join(str(query or "").split())
    if not clean_query:
        raise ValueError("query is required.")
    safe_limit = max(1, min(int(limit), 20))
    normalized_mode = mode.strip().lower() if mode else "hybrid"
    if normalized_mode not in {"hybrid", "vector", "graph"}:
        normalized_mode = "hybrid"

    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        if normalized_mode == "graph" or _looks_like_org_query(clean_query):
            graph_hits = _graph_search(db, clean_query, document_name=document_name, org_unit=org_unit)
            if graph_hits:
                return {
                    "query": clean_query,
                    "mode": "graph",
                    "results": graph_hits[:safe_limit],
                    "db_path": str(database),
                }

        vector_hits = _vector_search(
            db,
            clean_query,
            document_name=document_name,
            org_unit=org_unit,
            limit=max(safe_limit * 4, 12),
        )
        packed = _pack_hybrid_results(
            db,
            vector_hits,
            limit=safe_limit,
            include_graph=normalized_mode == "hybrid",
        )
    return {
        "query": clean_query,
        "mode": normalized_mode,
        "results": packed,
        "db_path": str(database),
    }


def explore_org(
    org_unit: str,
    *,
    db_path: str | Path | None = None,
    document_name: str | None = None,
    depth: int = 2,
) -> dict[str, Any]:
    database = Path(db_path or default_db_path())
    if not database.exists():
        return _not_indexed_response(database)
    clean_org = " ".join(str(org_unit or "").split())
    if not clean_org:
        raise ValueError("org_unit is required.")
    safe_depth = max(0, min(int(depth), 6))
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        rows = _find_org_nodes(db, clean_org, document_name=document_name)
        results = [
            _org_tree(db, row["node_id"], safe_depth)
            for row in rows[:20]
        ]
    return {
        "org_unit": clean_org,
        "document_name": document_name,
        "depth": safe_depth,
        "results": results,
        "db_path": str(database),
    }


def list_sources(db_path: str | Path | None = None, *, limit: int = 100) -> dict[str, Any]:
    database = Path(db_path or default_db_path())
    if not database.exists():
        return _not_indexed_response(database)
    safe_limit = max(1, min(int(limit), 500))
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """
            SELECT
                d.document_id,
                d.document_name,
                d.source_path,
                d.line_count,
                d.indexed_at,
                COUNT(DISTINCT c.chunk_id) AS chunk_count,
                COUNT(DISTINCT n.node_id) AS node_count
            FROM documents d
            LEFT JOIN chunks c ON c.document_id = d.document_id
            LEFT JOIN nodes n ON n.document_id = d.document_id
            GROUP BY d.document_id
            ORDER BY d.document_name, d.source_path
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        edge_counts = {
            row["document_id"]: int(row["edge_count"])
            for row in db.execute(
                "SELECT document_id, COUNT(*) AS edge_count FROM edges GROUP BY document_id"
            ).fetchall()
        }
    return {
        "db_path": str(database),
        "documents": [
            {
                "document_id": row["document_id"],
                "document_name": row["document_name"],
                "source_path": row["source_path"],
                "line_count": row["line_count"],
                "indexed_at": row["indexed_at"],
                "chunk_count": int(row["chunk_count"]),
                "node_count": int(row["node_count"]),
                "edge_count": edge_counts.get(row["document_id"], 0),
            }
            for row in rows
        ],
    }


def store_status(db_path: str | Path | None = None) -> dict[str, Any]:
    database = Path(db_path or default_db_path())
    if not database.exists():
        return {
            "ok": False,
            "db_path": str(database),
            "document_count": 0,
            "chunk_count": 0,
            "node_count": 0,
            "edge_count": 0,
            "message": "Vector GraphRAG database has not been indexed yet.",
        }
    with sqlite3.connect(database) as db:
        counts = {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("documents", "chunks", "nodes", "edges")
        }
    return {
        "ok": True,
        "db_path": str(database),
        "document_count": counts["documents"],
        "chunk_count": counts["chunks"],
        "node_count": counts["nodes"],
        "edge_count": counts["edges"],
    }


def clear_store(db_path: str | Path | None = None) -> dict[str, Any]:
    database = Path(db_path or default_db_path())
    if not database.exists():
        return store_status(database)
    with sqlite3.connect(database) as db:
        for table in ("edges", "chunks", "nodes", "documents"):
            db.execute(f"DELETE FROM {table}")
        db.commit()
    return store_status(database)


def _pending_to_blocks(pending: list[tuple[int, str]], heading_stack: tuple[Heading, ...]) -> list[Block]:
    blocks: list[Block] = []
    index = 0
    while index < len(pending):
        line_no, line = pending[index]
        if not line.strip():
            index += 1
            continue
        if _is_table_line(line):
            start = index
            while index < len(pending) and _is_table_line(pending[index][1]):
                index += 1
            blocks.append(_block_from_range("table", pending[start:index], heading_stack))
            continue
        if LIST_RE.match(line):
            start = index
            index += 1
            while index < len(pending):
                next_line = pending[index][1]
                if not next_line.strip():
                    break
                if LIST_RE.match(next_line) or next_line.startswith((" ", "\t")):
                    index += 1
                    continue
                break
            blocks.append(_block_from_range("list", pending[start:index], heading_stack))
            continue
        start = index
        index += 1
        while index < len(pending):
            next_line = pending[index][1]
            if not next_line.strip() or _is_table_line(next_line) or LIST_RE.match(next_line):
                break
            index += 1
        blocks.append(_block_from_range("text", pending[start:index], heading_stack))
    return blocks


def _block_from_range(kind: str, rows: list[tuple[int, str]], heading_stack: tuple[Heading, ...]) -> Block:
    return Block(
        kind=kind,
        text="\n".join(line for _line_no, line in rows).strip(),
        line_start=rows[0][0],
        line_end=rows[-1][0],
        heading_stack=heading_stack,
    )


def _split_large_block(block: Block, hard_limit_chars: int) -> list[Block]:
    if len(block.text) <= hard_limit_chars:
        return [block]
    if block.kind == "table":
        return _split_table_block(block, hard_limit_chars)
    rows = block.text.splitlines()
    parts: list[Block] = []
    current: list[str] = []
    start_line = block.line_start
    for offset, row in enumerate(rows):
        if current and len("\n".join(current + [row])) > hard_limit_chars:
            end_line = block.line_start + offset - 1
            parts.append(
                Block(block.kind, "\n".join(current).strip(), start_line, end_line, block.heading_stack)
            )
            current = []
            start_line = block.line_start + offset
        current.append(row)
    if current:
        parts.append(
            Block(block.kind, "\n".join(current).strip(), start_line, block.line_end, block.heading_stack)
        )
    return parts


def _split_table_block(block: Block, hard_limit_chars: int) -> list[Block]:
    rows = block.text.splitlines()
    if len(rows) <= 2:
        return _split_large_text_block(block, hard_limit_chars)
    header = rows[:2]
    body = rows[2:]
    parts: list[Block] = []
    current = header[:]
    start_line = block.line_start
    for row_index, row in enumerate(body, start=2):
        if len("\n".join(current + [row])) > hard_limit_chars and len(current) > len(header):
            end_line = block.line_start + row_index - 1
            parts.append(Block("table", "\n".join(current), start_line, end_line, block.heading_stack))
            current = header[:] + [row]
            start_line = block.line_start + row_index
        else:
            current.append(row)
    if len(current) > len(header):
        parts.append(Block("table", "\n".join(current), start_line, block.line_end, block.heading_stack))
    return parts or [block]


def _split_large_text_block(block: Block, hard_limit_chars: int) -> list[Block]:
    text = block.text
    parts = []
    for start in range(0, len(text), hard_limit_chars):
        parts.append(
            Block(block.kind, text[start : start + hard_limit_chars], block.line_start, block.line_end, block.heading_stack)
        )
    return parts


def _chunk_from_blocks(
    blocks: list[Block],
    *,
    index: int,
    document_id: str,
    document_name: str,
    source_path: str,
) -> Chunk:
    heading_stack = blocks[-1].heading_stack
    heading_path = tuple(heading.title for heading in heading_stack)
    org_path = _org_path(heading_path, document_name)
    section_title = heading_path[-1] if heading_path else document_name
    section_node_id = heading_stack[-1].node_id if heading_stack else f"doc:{document_id}"
    content_kind = blocks[0].kind if all(block.kind == blocks[0].kind for block in blocks) else "mixed"
    body = "\n\n".join(block.text for block in blocks if block.text.strip()).strip()
    text = _format_chunk_text(document_name, heading_path, org_path, body)
    chunk_id = f"chunk:{document_id}:{index}"
    chunk_node_id = f"chunk-node:{document_id}:{index}"
    return Chunk(
        chunk_id=chunk_id,
        chunk_node_id=chunk_node_id,
        section_node_id=section_node_id,
        document_id=document_id,
        document_name=document_name,
        source_path=source_path,
        heading_path=heading_path,
        org_path=org_path,
        section_title=section_title,
        content_kind=content_kind,
        line_start=min(block.line_start for block in blocks),
        line_end=max(block.line_end for block in blocks),
        text=text,
        embedding=embed_text(text),
    )


def embed_text(text: str, dimensions: int = DEFAULT_DIMENSIONS) -> array:
    vector = array("f", [0.0]) * dimensions
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8", errors="ignore"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm > 0:
        for index, value in enumerate(vector):
            vector[index] = value / norm
    return vector


def _tokens(text: str) -> Iterable[str]:
    lowered = text.casefold()
    for match in re.finditer(r"[a-z0-9_가-힣]{2,}", lowered):
        token = match.group(0)
        yield token
        if len(token) >= 3:
            for size in (2, 3):
                for index in range(0, len(token) - size + 1):
                    yield token[index : index + size]


def _insert_heading_graph(
    db: sqlite3.Connection,
    document_id: str,
    document_node_id: str,
    headings: list[Heading],
    line_count: int,
    document_name: str,
) -> None:
    previous_by_parent: dict[str, Heading] = {}
    heading_by_id = {heading.node_id: heading for heading in headings}
    for idx, heading in enumerate(headings):
        next_line = (
            min(
                (other.line for other in headings[idx + 1 :] if other.level <= heading.level),
                default=line_count + 1,
            )
            - 1
        )
        stack = _heading_stack_for(heading, heading_by_id)
        heading_path = tuple(item.title for item in stack)
        org_path = _org_path(heading_path, document_name)
        db.execute(
            """
            INSERT INTO nodes
                (node_id, document_id, node_type, name, heading_path, org_path, line_start, line_end)
            VALUES (?, ?, 'heading', ?, ?, ?, ?, ?)
            """,
            (
                heading.node_id,
                document_id,
                heading.title,
                _json_list(heading_path),
                _json_list(org_path),
                heading.line,
                max(heading.line, next_line),
            ),
        )
        parent_node_id = heading.parent_node_id or document_node_id
        _insert_edge(db, document_id, parent_node_id, heading.node_id, "contains")
        if heading.parent_node_id:
            _insert_edge(db, document_id, heading.parent_node_id, heading.node_id, "parent_of")
        parent_key = parent_node_id
        previous = previous_by_parent.get(parent_key)
        if previous is not None:
            _insert_edge(db, document_id, previous.node_id, heading.node_id, "next_sibling")
        previous_by_parent[parent_key] = heading


def _insert_chunk(db: sqlite3.Connection, chunk: Chunk) -> None:
    db.execute(
        """
        INSERT INTO nodes
            (node_id, document_id, node_type, name, heading_path, org_path, line_start, line_end)
        VALUES (?, ?, 'chunk', ?, ?, ?, ?, ?)
        """,
        (
            chunk.chunk_node_id,
            chunk.document_id,
            chunk.section_title,
            _json_list(chunk.heading_path),
            _json_list(chunk.org_path),
            chunk.line_start,
            chunk.line_end,
        ),
    )
    db.execute(
        """
        INSERT INTO chunks
            (
                chunk_id, chunk_node_id, section_node_id, document_id, document_name,
                source_path, heading_path, org_path, section_title, content_kind,
                line_start, line_end, text, embedding
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk.chunk_id,
            chunk.chunk_node_id,
            chunk.section_node_id,
            chunk.document_id,
            chunk.document_name,
            chunk.source_path,
            _json_list(chunk.heading_path),
            _json_list(chunk.org_path),
            chunk.section_title,
            chunk.content_kind,
            chunk.line_start,
            chunk.line_end,
            chunk.text,
            chunk.embedding.tobytes(),
        ),
    )
    _insert_edge(db, chunk.document_id, chunk.section_node_id, chunk.chunk_node_id, "contains")
    _insert_edge(db, chunk.document_id, chunk.chunk_node_id, chunk.section_node_id, "chunk_of")


def _insert_edge(
    db: sqlite3.Connection,
    document_id: str,
    source_node_id: str,
    target_node_id: str,
    edge_type: str,
) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO edges
            (document_id, source_node_id, target_node_id, edge_type)
        VALUES (?, ?, ?, ?)
        """,
        (document_id, source_node_id, target_node_id, edge_type),
    )


def _vector_search(
    db: sqlite3.Connection,
    query: str,
    *,
    document_name: str | None,
    org_unit: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if document_name:
        clauses.append("document_name = ?")
        params.append(document_name)
    if org_unit:
        clauses.append("(org_path LIKE ? OR heading_path LIKE ?)")
        needle = f"%{org_unit}%"
        params.extend([needle, needle])
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.execute(
        f"""
        SELECT * FROM chunks
        {where}
        """,
        params,
    ).fetchall()
    query_vector = embed_text(query)
    scored: list[dict[str, Any]] = []
    for row in rows:
        embedding = array("f")
        embedding.frombytes(row["embedding"])
        score = sum(left * right for left, right in zip(query_vector, embedding))
        if score <= 0:
            continue
        scored.append(_chunk_row_to_result(row, score))
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def _pack_hybrid_results(
    db: sqlite3.Connection,
    hits: list[dict[str, Any]],
    *,
    limit: int,
    include_graph: bool,
) -> list[dict[str, Any]]:
    packed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        key = f"{hit['document_id']}::{hit['heading_path_text']}"
        if key in seen and len(packed) >= limit:
            continue
        seen.add(key)
        item = dict(hit)
        if include_graph:
            item["graph_context"] = _graph_context_for_chunk(db, hit)
            item["expanded_context"] = _expanded_chunks_for_chunk(db, hit)
        packed.append(item)
        if len(packed) >= limit:
            break
    return packed


def _chunk_row_to_result(row: sqlite3.Row, score: float) -> dict[str, Any]:
    heading_path = _read_json_list(row["heading_path"])
    org_path = _read_json_list(row["org_path"])
    line_start = row["line_start"]
    line_end = row["line_end"]
    return {
        "chunk_id": row["chunk_id"],
        "chunk_node_id": row["chunk_node_id"],
        "section_node_id": row["section_node_id"],
        "document_id": row["document_id"],
        "document_name": row["document_name"],
        "source_path": row["source_path"],
        "source_label": row["document_name"],
        "citation": _source_citation(row["document_name"]),
        "excerpt": _source_excerpt(row["text"]),
        "source_chip": _source_chip(row["document_name"], row["document_id"], row["text"]),
        "lines": f"{line_start}-{line_end}",
        "line_start": line_start,
        "line_end": line_end,
        "heading_path": heading_path,
        "heading_path_text": " > ".join(heading_path),
        "org_path": org_path,
        "org_path_text": " > ".join(org_path),
        "section_title": row["section_title"],
        "content_kind": row["content_kind"],
        "score": round(score, 4),
        "text": row["text"],
    }


def _graph_context_for_chunk(db: sqlite3.Connection, hit: dict[str, Any]) -> list[dict[str, Any]]:
    section_id = hit["section_node_id"]
    related = []
    for edge_type, direction in (
        ("parent_of", "ancestor"),
        ("parent_of", "child"),
        ("next_sibling", "next_sibling"),
    ):
        if direction == "ancestor":
            rows = _ancestor_nodes(db, section_id)
        elif direction == "child":
            rows = db.execute(
                """
                SELECT n.* FROM edges e
                JOIN nodes n ON n.node_id = e.target_node_id
                WHERE e.source_node_id = ? AND e.edge_type = ?
                ORDER BY n.line_start
                LIMIT 8
                """,
                (section_id, edge_type),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT n.* FROM edges e
                JOIN nodes n ON n.node_id = e.target_node_id
                WHERE e.source_node_id = ? AND e.edge_type = ?
                ORDER BY n.line_start
                LIMIT 2
                """,
                (section_id, edge_type),
            ).fetchall()
        for row in rows:
            related.append(_node_summary(row, relation=direction))
    return related


def _expanded_chunks_for_chunk(db: sqlite3.Connection, hit: dict[str, Any]) -> list[dict[str, Any]]:
    section_ids = [item["node_id"] for item in _ancestor_nodes(db, hit["section_node_id"])[-1:]]
    section_ids.append(hit["section_node_id"])
    sibling_rows = db.execute(
        """
        SELECT target_node_id FROM edges
        WHERE source_node_id = ? AND edge_type = 'next_sibling'
        LIMIT 1
        """,
        (hit["section_node_id"],),
    ).fetchall()
    section_ids.extend(row["target_node_id"] for row in sibling_rows)
    placeholders = ",".join("?" for _ in section_ids)
    if not placeholders:
        return []
    rows = db.execute(
        f"""
        SELECT * FROM chunks
        WHERE section_node_id IN ({placeholders}) AND chunk_id != ?
        ORDER BY line_start
        LIMIT 3
        """,
        [*section_ids, hit["chunk_id"]],
    ).fetchall()
    return [
        {
            "document_name": row["document_name"],
            "source_path": row["source_path"],
            "source_label": row["document_name"],
            "citation": _source_citation(row["document_name"]),
            "excerpt": _source_excerpt(row["text"]),
            "source_chip": _source_chip(row["document_name"], row["document_id"], row["text"]),
            "lines": f"{row['line_start']}-{row['line_end']}",
            "heading_path": _read_json_list(row["heading_path"]),
            "text": _short_text(row["text"], 900),
        }
        for row in rows
    ]


def _graph_search(
    db: sqlite3.Connection,
    query: str,
    *,
    document_name: str | None,
    org_unit: str | None,
) -> list[dict[str, Any]]:
    target = org_unit or query
    nodes = _find_org_nodes(db, target, document_name=document_name)
    return [_org_tree(db, row["node_id"], 2) for row in nodes[:10]]


def _find_org_nodes(
    db: sqlite3.Connection,
    org_unit: str,
    *,
    document_name: str | None,
) -> list[sqlite3.Row]:
    exact_clauses = ["n.node_type = 'heading'", "n.name = ?"]
    exact_params: list[Any] = [org_unit]
    if document_name:
        exact_clauses.append("d.document_name = ?")
        exact_params.append(document_name)
    exact_rows = db.execute(
        f"""
        SELECT n.*, d.document_name, d.source_path
        FROM nodes n
        JOIN documents d ON d.document_id = n.document_id
        WHERE {' AND '.join(exact_clauses)}
        ORDER BY d.document_name, n.line_start
        """,
        exact_params,
    ).fetchall()
    if exact_rows:
        return exact_rows

    clauses = ["n.node_type = 'heading'", "(n.name LIKE ? OR n.org_path LIKE ? OR n.heading_path LIKE ?)"]
    params: list[Any] = [f"%{org_unit}%", f"%{org_unit}%", f"%{org_unit}%"]
    if document_name:
        clauses.append("d.document_name = ?")
        params.append(document_name)
    return db.execute(
        f"""
        SELECT n.*, d.document_name, d.source_path
        FROM nodes n
        JOIN documents d ON d.document_id = n.document_id
        WHERE {' AND '.join(clauses)}
        ORDER BY d.document_name, n.line_start
        """,
        params,
    ).fetchall()


def _org_tree(db: sqlite3.Connection, node_id: str, depth: int) -> dict[str, Any]:
    row = db.execute(
        """
        SELECT n.*, d.document_name, d.source_path
        FROM nodes n
        JOIN documents d ON d.document_id = n.document_id
        WHERE n.node_id = ?
        """,
        (node_id,),
    ).fetchone()
    if row is None:
        return {"node_id": node_id, "missing": True}
    children = []
    if depth > 0:
        child_rows = db.execute(
            """
            SELECT n.node_id FROM edges e
            JOIN nodes n ON n.node_id = e.target_node_id
            WHERE e.source_node_id = ? AND e.edge_type IN ('parent_of', 'contains')
              AND n.node_type = 'heading'
            ORDER BY n.line_start
            """,
            (node_id,),
        ).fetchall()
        children = [_org_tree(db, child["node_id"], depth - 1) for child in child_rows]
    return {
        **_node_summary(row),
        "document_name": row["document_name"],
        "source_path": row["source_path"],
        "source_label": row["document_name"],
        "citation": _source_citation(row["document_name"]),
        "children": children,
    }


def _ancestor_nodes(db: sqlite3.Connection, node_id: str) -> list[sqlite3.Row]:
    rows: list[sqlite3.Row] = []
    current = node_id
    for _ in range(8):
        parent = db.execute(
            """
            SELECT n.* FROM edges e
            JOIN nodes n ON n.node_id = e.source_node_id
            WHERE e.target_node_id = ? AND e.edge_type = 'parent_of'
            LIMIT 1
            """,
            (current,),
        ).fetchone()
        if parent is None:
            break
        rows.append(parent)
        current = parent["node_id"]
    rows.reverse()
    return rows


def _node_summary(row: sqlite3.Row, relation: str | None = None) -> dict[str, Any]:
    result = {
        "node_id": row["node_id"],
        "node_type": row["node_type"],
        "name": row["name"],
        "heading_path": _read_json_list(row["heading_path"]),
        "org_path": _read_json_list(row["org_path"]),
        "lines": f"{row['line_start']}-{row['line_end']}",
    }
    if relation:
        result["relation"] = relation
    return result


def _delete_document(db: sqlite3.Connection, document_id: str) -> None:
    for table in ("edges", "chunks", "nodes", "documents"):
        db.execute(f"DELETE FROM {table} WHERE document_id = ?", (document_id,))


def _document_name(path: Path, metadata: dict[str, Any], content_lines: list[str]) -> str:
    raw_name = metadata.get("document_name")
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip()
    for line in content_lines:
        match = HEADING_RE.match(line.strip())
        if match and len(match.group(1)) == 1:
            return _clean_heading_title(match.group(2)) or path.stem
    return path.stem


def _split_frontmatter(lines: list[str]) -> tuple[dict[str, Any], list[str]]:
    if not lines or lines[0].strip() != "---":
        return {}, lines
    for index in range(1, min(len(lines), 200)):
        if lines[index].strip() == "---":
            try:
                payload = yaml.safe_load("\n".join(lines[1:index])) or {}
            except yaml.YAMLError:
                payload = {}
            metadata = payload if isinstance(payload, dict) else {}
            return metadata, lines[index + 1 :]
    return {}, lines


def _frontmatter_end_line(lines: list[str]) -> int:
    if not lines or lines[0].strip() != "---":
        return 0
    for index in range(1, min(len(lines), 200)):
        if lines[index].strip() == "---":
            return index + 1
    return 0


def _heading_stack_for(heading: Heading, heading_by_id: dict[str, Heading]) -> tuple[Heading, ...]:
    stack = [heading]
    parent_id = heading.parent_node_id
    while parent_id:
        parent = heading_by_id.get(parent_id)
        if parent is None:
            break
        stack.append(parent)
        parent_id = parent.parent_node_id
    return tuple(reversed(stack))


def _org_path(heading_path: Iterable[str], document_name: str) -> tuple[str, ...]:
    parts = tuple(part for part in heading_path if part)
    if not parts:
        return ()
    if parts[0].casefold() == document_name.casefold():
        return parts[1:]
    return parts[1:] if len(parts) > 1 else parts


def _format_chunk_text(
    document_name: str,
    heading_path: tuple[str, ...],
    org_path: tuple[str, ...],
    body: str,
) -> str:
    prefix = [
        f"Document: {document_name}",
        f"Heading path: {' > '.join(heading_path) if heading_path else document_name}",
    ]
    if org_path:
        prefix.append(f"Organization path: {' > '.join(org_path)}")
    return "\n".join(prefix) + "\n\n" + body


def _relative_source_path(path: Path, documents_dir: Path) -> str:
    try:
        return path.resolve().relative_to(documents_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def _document_id(source_path: str) -> str:
    digest = hashlib.sha1(source_path.replace("\\", "/").casefold().encode("utf-8")).hexdigest()[:16]
    return f"doc-{digest}"


def _clean_heading_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().strip("#").strip())


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _json_list(values: Iterable[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False)


def _read_json_list(value: str) -> list[str]:
    try:
        payload = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in payload] if isinstance(payload, list) else []


def _short_text(text: str, limit: int) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _source_excerpt(text: str, limit: int = 220) -> str:
    return _short_text(re.sub(r"\s+", " ", str(text or "")).strip(), limit)


def _source_citation(document_name: str) -> str:
    return document_name


def _source_chip(document_name: str, document_id: str, text: str) -> str:
    label = _escape_markdown_link_label(f"출처: {document_name}")
    title = _source_excerpt(text).replace("\\", "\\\\").replace('"', '\\"')
    return f'[{label}](source:vector-db/{document_id} "{title}")'


def _escape_markdown_link_label(value: str) -> str:
    return str(value or "").replace("[", "\\[").replace("]", "\\]")


def _looks_like_org_query(query: str) -> bool:
    return any(token in query for token in ("조직", "본부", "실", "부서", "팀", "산하", "계층", "업무 뭐"))


def _not_indexed_response(db_path: Path) -> dict[str, Any]:
    return {
        "ok": False,
        "db_path": str(db_path),
        "message": "Vector GraphRAG database has not been indexed yet. Run `python extensions/mcp/vector-db/runtime/ingest.py index` first.",
        "results": [],
    }


def _to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the local Vector GraphRAG SQLite store.")
    parser.add_argument("--db", default=str(default_db_path()), help="SQLite database path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Index Markdown/text documents.")
    index_parser.add_argument("--documents", default=str(default_documents_dir()), help="Documents directory.")
    index_parser.add_argument("--target-chars", type=int, default=DEFAULT_TARGET_CHARS)
    index_parser.add_argument("--hard-limit-chars", type=int, default=DEFAULT_HARD_LIMIT_CHARS)

    search_parser = subparsers.add_parser("search", help="Search indexed chunks.")
    search_parser.add_argument("query")
    search_parser.add_argument("--document-name")
    search_parser.add_argument("--org-unit")
    search_parser.add_argument("--mode", default="hybrid", choices=["hybrid", "vector", "graph"])
    search_parser.add_argument("--limit", type=int, default=5)

    org_parser = subparsers.add_parser("explore-org", help="Explore organization hierarchy.")
    org_parser.add_argument("org_unit")
    org_parser.add_argument("--document-name")
    org_parser.add_argument("--depth", type=int, default=2)

    subparsers.add_parser("sources", help="List indexed documents.")
    subparsers.add_parser("status", help="Show store status.")
    subparsers.add_parser("clear", help="Clear all indexed data.")

    args = parser.parse_args(argv)
    db_path = Path(args.db)
    if args.command == "index":
        result = index_directory(
            args.documents,
            db_path,
            target_chars=args.target_chars,
            hard_limit_chars=args.hard_limit_chars,
        )
    elif args.command == "search":
        result = retrieve_context(
            args.query,
            db_path=db_path,
            document_name=args.document_name,
            org_unit=args.org_unit,
            mode=args.mode,
            limit=args.limit,
        )
    elif args.command == "explore-org":
        result = explore_org(
            args.org_unit,
            db_path=db_path,
            document_name=args.document_name,
            depth=args.depth,
        )
    elif args.command == "sources":
        result = list_sources(db_path)
    elif args.command == "status":
        result = store_status(db_path)
    elif args.command == "clear":
        result = clear_store(db_path)
    else:
        raise AssertionError(args.command)
    sys.stdout.write(_to_json(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
