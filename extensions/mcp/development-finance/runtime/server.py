"""Official development-finance indicators with a stable structured API contract."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime

from mcp.server.fastmcp import FastMCP

from official_data import (
    checked_health_envelope,
    clean_limit,
    request,
    request_json,
    result_envelope,
    safe_identifier,
)


ADB_KIDB_BASE_URL = "https://kidb.adb.org/api"
SOURCES = {"adb_kidb": "Asian Development Bank Key Indicators Database"}

server = FastMCP("development-finance")


def _source(source: str) -> str:
    key = source.strip().lower().replace("-", "_")
    if key in {"adb", "kidb"}:
        key = "adb_kidb"
    if key not in SOURCES:
        raise ValueError("Unknown source. Use adb_kidb; World Bank uses the existing worldbank MCP.")
    return key


def _token(value: str, *, name: str, pattern: str) -> str:
    return safe_identifier(value, field_name=name, pattern=pattern)


@server.tool()
def search_catalog(source: str, dataflow: str, query: str = "", limit: int = 100) -> str:
    """List ADB KIDB indicators within an official dataflow."""
    selected = _source(source)
    flow = _token(dataflow.upper(), name="dataflow", pattern=r"[A-Z0-9_]{2,40}")
    payload = request_json(
        "ADB KIDB",
        f"{ADB_KIDB_BASE_URL}/dataflow/indicators/{flow}",
        timeout=60,
    )
    rows = payload if isinstance(payload, list) else []
    needle = query.casefold().strip()
    data = [
        row
        for row in rows
        if isinstance(row, dict)
        and (not needle or needle in json.dumps(row, ensure_ascii=False).casefold())
    ][: clean_limit(limit, maximum=500)]
    return result_envelope(
        source=SOURCES[selected],
        source_id=f"dataflow/indicators/{flow}",
        data=data,
        completeness="dataflow_catalog_query_limited",
        license_name="ADB data terms",
    )


@server.tool()
def query_series(
    source: str,
    dataflow: str,
    indicators: str,
    economies: str,
    start_period: int | None = None,
    end_period: int | None = None,
    limit: int = 1000,
) -> str:
    """Query annual ADB indicators; indicators/economies are plus-separated official codes."""
    selected = _source(source)
    flow = _token(dataflow.upper(), name="dataflow", pattern=r"[A-Z0-9_]{2,40}")
    indicator_codes = _token(
        indicators.upper(), name="indicators", pattern=r"[A-Z0-9_]+(?:\+[A-Z0-9_]+){0,19}"
    )
    economy_codes = _token(
        economies.upper(), name="economies", pattern=r"[A-Z0-9_]+(?:\+[A-Z0-9_]+){0,19}"
    )
    if start_period is None or end_period is None:
        raise ValueError("start_period and end_period are required for bounded ADB queries.")
    current_year = datetime.now(UTC).year
    if not 1900 <= int(start_period) <= current_year + 5:
        raise ValueError("start_period is outside the supported year range.")
    if not 1900 <= int(end_period) <= current_year + 5:
        raise ValueError("end_period is outside the supported year range.")
    if int(end_period) < int(start_period):
        raise ValueError("end_period must not be earlier than start_period.")
    if int(end_period) - int(start_period) >= 50:
        raise ValueError("ADB queries must cover at most 50 years.")
    response = request(
        "ADB KIDB",
        f"{ADB_KIDB_BASE_URL}/v4/sdmx/data/ADB,{flow}/A.{indicator_codes}.{economy_codes}",
        params={
            "startPeriod": int(start_period) if start_period is not None else None,
            "endPeriod": int(end_period) if end_period is not None else None,
            "format": "sdmx-csv",
        },
        headers={"Accept": "text/csv"},
        timeout=60,
    )
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    data = rows[: clean_limit(limit, maximum=5000)]
    return result_envelope(
        source=SOURCES[selected],
        source_id=f"ADB,{flow}/A.{indicator_codes}.{economy_codes}",
        data=data,
        as_of=str(end_period) if end_period else None,
        unit=data[0].get("UNIT") if data else None,
        revision="latest_returned_by_api",
        completeness="caller_filtered_sdmx_csv",
        license_name="ADB data terms",
    )


@server.tool()
def get_source_health(source: str) -> str:
    """Perform a small no-key query against the official ADB KIDB API."""
    selected = _source(source)
    return checked_health_envelope(
        source=SOURCES[selected],
        probe=lambda: request_json(
            "ADB KIDB", f"{ADB_KIDB_BASE_URL}/dataflow/indicators/PPL_POP", timeout=60
        ),
        success_detail="ADB KIDB v4 SDMX API is reachable; public limit is 20 requests per minute.",
    )


@server.resource("development-finance://overview", name="Development finance MCP overview")
def overview() -> str:
    """Describe stable APIs and explain why disclosure portals are not scraped."""
    return json.dumps(
        {
            "sources": SOURCES,
            "routing": {
                "World Bank indicators": "existing worldbank MCP",
                "ADB regional/economy indicators": "adb_kidb",
            },
            "excluded_project_portals": ["IFC", "MIGA", "AIIB", "EBRD", "IDB projects", "AfDB projects"],
            "exclusion_reason": (
                "Project disclosure portals do not publish a stable documented record API; "
                "material is primarily HTML, PDF, or spreadsheet downloads and would require fragile scraping."
            ),
            "document_policy": "Structured SDMX CSV/JSON only; no project PDF or OCR extraction.",
        },
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    server.run("stdio")
