"""Vector GraphRAG MCP server for local organization Markdown knowledge."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store import (
    default_db_path,
    explore_org as store_explore_org,
    list_sources as store_list_sources,
    retrieve_context as store_retrieve_context,
    store_status as store_store_status,
)


server = FastMCP("vector_db")


def _db_path() -> Path:
    override = os.environ.get("VECTOR_DB_RAG_DB_PATH", "").strip()
    return Path(override).expanduser() if override else default_db_path()


def _to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@server.tool()
def retrieve_context(
    query: str,
    document_name: str | None = None,
    org_unit: str | None = None,
    mode: str = "hybrid",
    limit: int = 5,
) -> str:
    """Retrieve context from the local organization knowledge base using vector, graph, or hybrid search."""
    return _to_json(
        store_retrieve_context(
            query,
            db_path=_db_path(),
            document_name=document_name,
            org_unit=org_unit,
            mode=mode,
            limit=limit,
        )
    )


@server.tool()
def explore_org(org_unit: str, document_name: str | None = None, depth: int = 2) -> str:
    """Explore parent, child, and sibling organization/work sections for one organization unit."""
    return _to_json(
        store_explore_org(
            org_unit,
            db_path=_db_path(),
            document_name=document_name,
            depth=depth,
        )
    )


@server.tool()
def list_sources(limit: int = 100) -> str:
    """List indexed source documents with chunk, graph node, and graph edge counts."""
    return _to_json(store_list_sources(_db_path(), limit=limit))


@server.tool()
def store_status() -> str:
    """Return Vector GraphRAG store status and index counts."""
    return _to_json(store_store_status(_db_path()))


@server.resource("vector-db://overview", name="Vector GraphRAG overview")
def overview() -> str:
    """Describe the local Vector GraphRAG MCP server."""
    return _to_json(
        {
            "service": "Vector GraphRAG",
            "db_path": str(_db_path()),
            "tools": [
                "retrieve_context",
                "explore_org",
                "list_sources",
                "store_status",
            ],
            "index_command": "python extensions/mcp/vector-db/runtime/ingest.py index",
            "documents_dir": str(Path(__file__).resolve().parent / "documents"),
            "notes": [
                "Markdown heading hierarchy is stored as graph nodes and edges.",
                "Every chunk keeps document_name, source_path, heading_path, org_path, and line range metadata.",
                "Use retrieve_context for detailed business questions and explore_org for hierarchy questions.",
            ],
            "status": store_store_status(_db_path()),
        }
    )


if __name__ == "__main__":
    server.run("stdio")
