"""Official macro-finance MCP for FRED, ECB, BIS, NY Fed, OECD, and e-Stat."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from functools import partial
from typing import Any

from mcp.server.fastmcp import FastMCP

from official_data import (
    checked_health_envelope,
    clean_limit,
    first_env,
    request,
    request_json,
    result_envelope,
    safe_identifier,
)


FRED_BASE_URL = "https://api.stlouisfed.org/fred"
ECB_BASE_URL = "https://data-api.ecb.europa.eu/service"
BIS_BASE_URL = "https://stats.bis.org/api/v2"
NYFED_BASE_URL = "https://markets.newyorkfed.org/api"
OECD_BASE_URL = "https://sdmx.oecd.org/public/rest"
ESTAT_BASE_URL = "https://api.e-stat.go.jp/rest/3.0/app/json"

SOURCES = {
    "fred": "Federal Reserve Bank of St. Louis FRED",
    "ecb": "European Central Bank Data Portal",
    "bis": "Bank for International Settlements Statistics",
    "nyfed": "Federal Reserve Bank of New York Markets",
    "oecd": "OECD Data Explorer",
    "estat_jp": "Statistics Bureau of Japan e-Stat",
}

server = FastMCP("macro-finance")


def _source(source: str) -> str:
    key = source.strip().lower().replace("-", "_")
    aliases = {"e_stat": "estat_jp", "estat": "estat_jp", "new_york_fed": "nyfed"}
    key = aliases.get(key, key)
    if key not in SOURCES:
        raise ValueError(f"Unknown source {source!r}. Use one of: {', '.join(SOURCES)}")
    return key


def _required_env(message: str, *names: str) -> str:
    value = first_env(*names)
    if not value:
        raise ValueError(message)
    return value


def _fred_key() -> str:
    return _required_env("FRED_API_KEY is required for FRED.", "FRED_API_KEY")


def _estat_key() -> str:
    return _required_env("ESTAT_JP_APP_ID is required for Japan e-Stat.", "ESTAT_JP_APP_ID")


def _csv_rows(content: bytes, limit: int) -> list[dict[str, str]]:
    text = content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))[: clean_limit(limit, maximum=5000)]


def _sdmx_token(value: str, *, field_name: str) -> str:
    return safe_identifier(
        value,
        field_name=field_name,
        pattern=r"[A-Za-z0-9_@,+.-]+",
    )


def _fred_json(path: str, params: dict[str, Any]) -> object:
    return request_json(
        "FRED",
        f"{FRED_BASE_URL}/{path}",
        params={"api_key": _fred_key(), "file_type": "json", **params},
    )


def _estat_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = request_json(
        "Japan e-Stat",
        f"{ESTAT_BASE_URL}/{path}",
        params={"appId": _estat_key(), "lang": "E", **params},
    )
    if not isinstance(payload, dict):
        raise ValueError("Japan e-Stat returned an unexpected JSON shape.")
    root = next((value for key, value in payload.items() if key.startswith("GET_")), None)
    result = root.get("RESULT", {}) if isinstance(root, dict) else {}
    status = str(result.get("STATUS", "0"))
    if status not in {"0", "00"}:
        raise ValueError(f"Japan e-Stat API error {status}: {result.get('ERROR_MSG', '')}")
    return payload


def _nyfed_path(series: str) -> str:
    selected = series.strip().lower()
    if selected in {"sofr", "tgcr", "bgcr"}:
        return f"rates/secured/{selected}/search.json"
    if selected == "obfr":
        return "rates/unsecured/obfr/search.json"
    raise ValueError("NY Fed series must be SOFR, TGCR, BGCR, RRP, or OBFR.")


def _period_bounds(
    start_period: str | None,
    end_period: str | None,
    *,
    source: str,
) -> tuple[str, str]:
    """Require a bounded ISO year/month/day range for potentially large series."""
    if not start_period or not end_period:
        raise ValueError(f"start_period and end_period are required for {source} queries.")
    values = []
    patterns = (
        (r"\d{4}", "%Y"),
        (r"\d{4}-\d{2}", "%Y-%m"),
        (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
    )
    for field_name, raw in (("start_period", start_period), ("end_period", end_period)):
        token = raw.strip()
        matched = next((date_format for pattern, date_format in patterns if re.fullmatch(pattern, token)), None)
        if not matched:
            raise ValueError(f"{field_name} must be YYYY, YYYY-MM, or YYYY-MM-DD.")
        datetime.strptime(token, matched)
        values.append(token)
    if values[1] < values[0]:
        raise ValueError("end_period must not be earlier than start_period.")
    return values[0], values[1]


@server.tool()
def search_catalog(source: str, query: str = "", limit: int = 50) -> str:
    """Search series or datasets and return identifiers needed by query_series."""
    selected = _source(source)
    safe_limit = clean_limit(limit, maximum=500)
    if selected == "fred":
        payload = _fred_json(
            "series/search",
            {"search_text": query, "limit": safe_limit, "order_by": "search_rank"},
        )
        data: object = payload.get("seriess", []) if isinstance(payload, dict) else payload
        source_id = "series/search"
    elif selected == "bis":
        payload = request_json(
            "BIS Statistics",
            f"{BIS_BASE_URL}/structure/dataflow/BIS/all/latest",
        )
        rows = payload.get("data", {}).get("dataflows", []) if isinstance(payload, dict) else []
        needle = query.casefold().strip()
        data = [
            row
            for row in rows
            if isinstance(row, dict)
            and (not needle or needle in f"{row.get('id', '')} {row.get('name', '')}".casefold())
        ][:safe_limit]
        source_id = "BIS/dataflows"
    elif selected == "estat_jp":
        payload = _estat_json(
            "getStatsList",
            {"searchWord": query, "limit": safe_limit, "searchKind": 1},
        )
        root = payload.get("GET_STATS_LIST", {})
        data = root.get("DATALIST_INF", {}).get("TABLE_INF", []) if isinstance(root, dict) else []
        source_id = "getStatsList"
    else:
        presets = {
            "ecb": {
                "EXR": "Exchange rates; example key D.USD.EUR.SP00.A",
                "FM": "Financial market data",
                "MIR": "Monetary financial institution interest rates",
            },
            "nyfed": {"SOFR": "Secured Overnight Financing Rate", "OBFR": "Overnight Bank Funding Rate", "TGCR": "Tri-Party General Collateral Rate", "BGCR": "Broad General Collateral Rate", "RRP": "Reverse repo operation results"},
            "oecd": {
                "OECD.SDD.STES,DSD_STES@DF_CLI": "Composite leading indicators",
                "OECD.SDD.STES,DSD_STES@DF_FINMARK": "Financial market indicators",
                "OECD.SDD.NAD,DSD_NAAG@DF_NAAG_I": "National accounts aggregates",
            },
        }[selected]
        needle = query.casefold().strip()
        data = [
            {"id": key, "description": value}
            for key, value in presets.items()
            if not needle or needle in f"{key} {value}".casefold()
        ][:safe_limit]
        source_id = "curated_official_presets"
    return result_envelope(
        source=SOURCES[selected],
        source_id=source_id,
        data=data,
        completeness="bounded_catalog_search",
        license_name="Official source reuse terms",
    )


@server.tool()
def query_series(
    source: str,
    series_id: str,
    start_period: str | None = None,
    end_period: str | None = None,
    dataset: str | None = None,
    limit: int = 1000,
    filters_json: dict[str, Any] | str | None = None,
) -> str:
    """Query a source series; SDMX sources require dataset plus source-native series key."""
    selected = _source(source)
    safe_limit = clean_limit(limit, maximum=5000)
    if selected == "fred":
        start_period, end_period = _period_bounds(start_period, end_period, source="FRED")
        series = safe_identifier(series_id, field_name="series_id", pattern=r"[A-Za-z0-9_.-]+")
        payload = _fred_json(
            "series/observations",
            {
                "series_id": series,
                "observation_start": start_period,
                "observation_end": end_period,
                "limit": safe_limit,
                "sort_order": "asc",
            },
        )
        data: object = payload.get("observations", []) if isinstance(payload, dict) else payload
        unit = None
        source_id = series
    elif selected == "ecb":
        start_period, end_period = _period_bounds(start_period, end_period, source="ECB")
        if not dataset:
            raise ValueError("dataset is required for ECB, for example EXR.")
        flow = _sdmx_token(dataset, field_name="dataset")
        key = safe_identifier(series_id, field_name="series_id", pattern=r"[A-Za-z0-9_.+-]+")
        response = request(
            "ECB Data Portal",
            f"{ECB_BASE_URL}/data/{flow}/{key}",
            params={
                "startPeriod": start_period,
                "endPeriod": end_period,
                "format": "csvdata",
            },
            timeout=60,
        )
        data = _csv_rows(response.content, safe_limit)
        unit = data[0].get("UNIT") if data else None
        source_id = f"{flow}/{key}"
    elif selected == "bis":
        start_period, end_period = _period_bounds(start_period, end_period, source="BIS")
        if not dataset:
            raise ValueError("dataset is required for BIS, for example WS_LONG_CPI.")
        flow = _sdmx_token(dataset, field_name="dataset")
        key = safe_identifier(series_id, field_name="series_id", pattern=r"[A-Za-z0-9_.+-]+")
        response = request(
            "BIS Statistics",
            f"{BIS_BASE_URL}/data/dataflow/BIS/{flow}/1.0/{key}",
            params={"startPeriod": start_period, "endPeriod": end_period},
            headers={"Accept": "application/vnd.sdmx.data+csv;version=2.0.0"},
            timeout=60,
        )
        data = _csv_rows(response.content, safe_limit)
        unit = data[0].get("UNIT_MEASURE") if data else None
        source_id = f"{flow}/{key}"
    elif selected == "nyfed":
        start_period, end_period = _period_bounds(start_period, end_period, source="NY Fed")
        if series_id.strip().lower() == "rrp":
            path = "rp/results/search.json"
            payload = request_json(
                "New York Fed Markets",
                f"{NYFED_BASE_URL}/{path}",
                params={
                    "startDate": start_period,
                    "endDate": end_period,
                    "operationTypes": "Reverse Repo",
                },
            )
            repo = payload.get("repo", {}) if isinstance(payload, dict) else {}
            rows = repo.get("operations", []) if isinstance(repo, dict) else []
            unit = "USD and percent as labeled by source"
        else:
            path = _nyfed_path(series_id)
            payload = request_json(
                "New York Fed Markets",
                f"{NYFED_BASE_URL}/{path}",
                params={"startDate": start_period, "endDate": end_period, "type": "rate"},
            )
            rows = payload.get("refRates", []) if isinstance(payload, dict) else []
            unit = "percent"
        if not isinstance(rows, list):
            raise ValueError("New York Fed returned an unexpected response shape.")
        data = rows[:safe_limit]
        source_id = series_id.upper()
    elif selected == "oecd":
        start_period, end_period = _period_bounds(start_period, end_period, source="OECD")
        if not dataset:
            raise ValueError("dataset is required for OECD.")
        flow = _sdmx_token(dataset, field_name="dataset")
        key = safe_identifier(series_id, field_name="series_id", pattern=r"[A-Za-z0-9_.+-]+")
        response = request(
            "OECD Data Explorer",
            f"{OECD_BASE_URL}/data/{flow}/{key}",
            params={
                "startPeriod": start_period,
                "endPeriod": end_period,
                "dimensionAtObservation": "AllDimensions",
                "format": "csvfilewithlabels",
            },
            timeout=90,
        )
        data = _csv_rows(response.content, safe_limit)
        unit = data[0].get("Unit of measure") if data else None
        source_id = f"{flow}/{key}"
    else:
        stats_id = safe_identifier(series_id, field_name="statsDataId", pattern=r"[A-Za-z0-9_-]+")
        extra: dict[str, Any] = {}
        if filters_json:
            parsed = filters_json if isinstance(filters_json, dict) else json.loads(filters_json)
            if not isinstance(parsed, dict):
                raise ValueError("filters_json must decode to an object.")
            for key, value in parsed.items():
                if not re.fullmatch(r"(cd|lv|cycle|start|end)[A-Za-z0-9_]*", str(key)):
                    raise ValueError(f"Unsupported e-Stat filter name: {key}")
                extra[str(key)] = value
        payload = _estat_json(
            "getStatsData",
            {"statsDataId": stats_id, "limit": safe_limit, **extra},
        )
        data = payload.get("GET_STATS_DATA", {}).get("STATISTICAL_DATA", {})
        unit = None
        source_id = stats_id
    return result_envelope(
        source=SOURCES[selected],
        source_id=source_id,
        data=data,
        as_of=end_period,
        unit=unit,
        revision="latest_returned_by_source",
        completeness="row_limited" if safe_limit < 5000 else "source_response",
        license_name="Official source reuse terms",
    )


@server.tool()
def get_source_health(source: str) -> str:
    """Check a macro source or safely report its missing credential."""
    selected = _source(source)
    credentials = {
        "fred": ("FRED_API_KEY",),
        "estat_jp": ("ESTAT_JP_APP_ID",),
        "ecb": (),
        "bis": (),
        "nyfed": (),
        "oecd": (),
    }[selected]
    if selected == "ecb":
        probe = partial(
            query_series,
            "ecb", "D.USD.EUR.SP00.A", "2025-01-01", "2025-01-05", "EXR", 2
        )
    elif selected == "bis":
        probe = partial(query_series, "bis", "A.DE.", "2023", "2024", "WS_LONG_CPI", 2)
    elif selected == "nyfed":
        probe = partial(
            query_series,
            "nyfed", "SOFR", "2025-01-02", "2025-01-10", limit=2
        )
    elif selected == "oecd":
        probe = partial(
            query_series,
            "oecd",
            "KOR.M.LI...AA...H",
            "2024-01",
            "2024-02",
            "OECD.SDD.STES,DSD_STES@DF_CLI",
            2,
        )
    elif selected == "fred":
        probe = partial(
            query_series,
            "fred", "DFF", "2025-01-01", "2025-01-03", limit=3
        )
    else:
        probe = partial(search_catalog, "estat_jp", "industrial production", 1)
    return checked_health_envelope(
        source=SOURCES[selected],
        credential_env=credentials,
        probe=probe,
        success_detail="Official endpoint is reachable.",
    )


@server.resource("macro-finance://overview", name="Macro finance MCP overview")
def overview() -> str:
    """Describe macro-finance source routing and representative datasets."""
    return json.dumps(
        {
            "sources": SOURCES,
            "tools": ["search_catalog", "query_series", "get_source_health"],
            "routing": {
                "U.S. macro series": "fred",
                "euro exchange, money, bank lending": "ecb",
                "international credit, liquidity, debt": "bis",
                "SOFR and repo market rates": "nyfed",
                "cross-country leading and industrial indicators": "oecd",
                "Japan official statistics": "estat_jp",
                "Korea official macro data": "existing ECOS and KOSIS MCPs",
            },
        },
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    server.run("stdio")
