"""Official industrial production, farm finance, and environmental compliance MCP."""

from __future__ import annotations

import json
from functools import partial
from typing import Any

from mcp.server.fastmcp import FastMCP

from official_data import (
    checked_health_envelope,
    clean_limit,
    first_env,
    request_json,
    result_envelope,
    safe_identifier,
)


EUROSTAT_PRODCOM_BASE_URL = (
    "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data"
)
EPA_ECHO_BASE_URL = "https://echodata.epa.gov/echo"
USDA_ERS_BASE_URL = "https://api.ers.usda.gov/data/arms"

SOURCES = {
    "eurostat_prodcom": "Eurostat PRODCOM",
    "epa_echo": "U.S. EPA ECHO",
    "usda_ers": "USDA Economic Research Service ARMS",
}

server = FastMCP("environment-industry")


def _source(source: str) -> str:
    key = source.strip().lower().replace("-", "_")
    aliases = {"prodcom": "eurostat_prodcom", "echo": "epa_echo", "ers": "usda_ers"}
    key = aliases.get(key, key)
    if key not in SOURCES:
        raise ValueError(f"Unknown source {source!r}. Use one of: {', '.join(SOURCES)}")
    return key


def _ers_key() -> str:
    key = first_env("USDA_ERS_API_KEY", "DATA_GOV_API_KEY")
    if not key:
        raise ValueError("USDA_ERS_API_KEY or DATA_GOV_API_KEY is required for USDA ERS.")
    return key


def _json_object(raw: dict[str, Any] | str | None, *, name: str) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object.")
    return value


def _bounded_filters(filters: dict[str, Any], *, allowed: set[str]) -> dict[str, Any]:
    unknown = sorted(set(filters) - allowed)
    if unknown:
        raise ValueError(f"Unsupported filter names: {', '.join(unknown)}")
    bounded: dict[str, Any] = {}
    for key, value in filters.items():
        if isinstance(value, (dict, list)):
            raise ValueError(f"Filter {key} must be a single scalar value.")
        if value is not None and len(str(value)) > 100:
            raise ValueError(f"Filter {key} is too long.")
        bounded[key] = value
    return bounded


@server.tool()
def search_catalog(source: str, query: str = "", limit: int = 50) -> str:
    """Search product/variable catalogs or return supported official dataset identifiers."""
    selected = _source(source)
    safe_limit = clean_limit(limit, maximum=500)
    if selected == "usda_ers":
        payload = request_json(
            "USDA ERS",
            f"{USDA_ERS_BASE_URL}/variable",
            params={"api_key": _ers_key(), "keyword": query or None},
        )
        data: object = payload[:safe_limit] if isinstance(payload, list) else payload
        source_id = "variable"
    else:
        catalog = {
            "eurostat_prodcom": [
                {"dataset": "DS-059358", "description": "Sold production, exports and imports"},
                {"dimensions": ["freq", "reporter", "product", "indicators", "time"]},
            ],
            "epa_echo": [
                "All Media Programs facility search",
                "CAA/CWA/RCRA/SDWA compliance status",
                "inspection and enforcement summary",
            ],
        }[selected]
        needle = query.casefold().strip()
        data = [
            item
            for item in catalog
            if not needle or needle in json.dumps(item, ensure_ascii=False).casefold()
        ][:safe_limit]
        source_id = "supported_datasets"
    return result_envelope(
        source=SOURCES[selected],
        source_id=source_id,
        data=data,
        completeness="bounded_catalog",
        license_name="Official source reuse terms",
    )


@server.tool()
def query_industry(
    source: str,
    dataset: str = "DS-059358",
    filters_json: dict[str, Any] | str | None = None,
    limit: int = 100,
) -> str:
    """Query filtered PRODCOM JSON-stat or USDA ERS ARMS survey data."""
    selected = _source(source)
    filters = _json_object(filters_json, name="filters_json")
    safe_limit = clean_limit(limit, maximum=1000)
    if selected == "eurostat_prodcom":
        code = safe_identifier(dataset.upper(), field_name="dataset", pattern=r"DS-\d{6}")
        if code != "DS-059358":
            raise ValueError("Only the verified PRODCOM dataset DS-059358 is supported.")
        filters = _bounded_filters(
            filters,
            allowed={"freq", "reporter", "product", "indicators", "time"},
        )
        missing = [name for name in ("reporter", "product", "time") if not filters.get(name)]
        if missing:
            raise ValueError(
                "PRODCOM requires reporter, product, and time filters to prevent an oversized query."
            )
        payload: object = request_json(
            "Eurostat PRODCOM",
            f"{EUROSTAT_PRODCOM_BASE_URL}/{code}",
            params={"lang": "en", **filters},
            timeout=90,
        )
        source_id = code
        revision = payload.get("updated") if isinstance(payload, dict) else None
        values = payload.get("value") if isinstance(payload, dict) else None
        observation_count = len(values) if isinstance(values, (dict, list)) else 0
        if observation_count > safe_limit:
            raise ValueError(
                f"PRODCOM returned {observation_count} observations, above limit={safe_limit}; "
                "narrow reporter, product, indicator, or time filters."
            )
    elif selected == "usda_ers":
        filters = _bounded_filters(
            filters,
            allowed={
                "year",
                "state",
                "report",
                "variable",
                "farmtype",
                "category",
                "category_value",
                "category2",
                "category2_value",
            },
        )
        if not filters.get("year") or not (filters.get("report") or filters.get("variable")):
            raise ValueError("USDA ERS surveydata requires year and either report or variable.")
        payload = request_json(
            "USDA ERS",
            f"{USDA_ERS_BASE_URL}/surveydata",
            params={"api_key": _ers_key(), **filters},
            timeout=60,
        )
        if isinstance(payload, list):
            payload = payload[:safe_limit]
        source_id = "surveydata"
        revision = "latest_returned_by_api"
    else:
        raise ValueError("EPA ECHO uses search_facilities and get_facility, not query_industry.")
    return result_envelope(
        source=SOURCES[selected],
        source_id=source_id,
        data=payload,
        revision=revision,
        completeness="caller_filtered_structured_data",
        license_name="Official source reuse terms",
    )


@server.tool()
def search_facilities(
    facility_name: str,
    state: str | None = None,
    registry_id: str | None = None,
    limit: int = 20,
) -> str:
    """Search EPA-regulated facilities and return compliance/enforcement summary fields."""
    name = facility_name.strip()
    if len(name) < 2 or len(name) > 100:
        raise ValueError("facility_name must contain 2 to 100 characters.")
    state_code = (
        safe_identifier(state.upper(), field_name="state", pattern=r"[A-Z]{2}") if state else None
    )
    frs = (
        safe_identifier(registry_id, field_name="registry_id", pattern=r"\d{8,20}")
        if registry_id
        else None
    )
    safe_limit = clean_limit(limit, maximum=100)
    payload = request_json(
        "EPA ECHO",
        f"{EPA_ECHO_BASE_URL}/echo_rest_services.get_facility_info",
        params={
            "output": "JSON",
            "p_fn": name,
            "p_st": state_code,
            "p_frs": frs,
            # ECHO's response set selects a documented field bundle; it is not a row limit.
            "responseset": "500",
        },
        timeout=60,
    )
    results = payload.get("Results", {}) if isinstance(payload, dict) else {}
    if not isinstance(results, dict):
        raise ValueError("EPA ECHO returned an unexpected response shape.")
    if results.get("ErrorMessage"):
        raise ValueError("EPA ECHO rejected the facility query.")
    data = results.get("Facilities", []) if isinstance(results, dict) else []
    if not isinstance(data, list):
        raise ValueError("EPA ECHO response is missing a Facilities list.")
    data = data[:safe_limit]
    return result_envelope(
        source=SOURCES["epa_echo"],
        source_id="echo_rest_services.get_facility_info",
        data=data,
        revision=results.get("Version") if isinstance(results, dict) else None,
        completeness="query_and_page_limited",
        license_name="U.S. government public data",
        metadata={
            "query_rows": results.get("QueryRows") if isinstance(results, dict) else None,
            "query_id": results.get("QueryID") if isinstance(results, dict) else None,
        },
    )


@server.tool()
def get_source_health(source: str) -> str:
    """Perform a lightweight official endpoint check and safely report credential needs."""
    selected = _source(source)
    if selected == "eurostat_prodcom":
        probe = partial(
            request_json,
            "Eurostat PRODCOM", f"{EUROSTAT_PRODCOM_BASE_URL}/DS-059358",
            params={"lang": "en", "reporter": "DE", "product": "00000000", "time": "2024"},
            timeout=60,
        )
        credential = ()
        detail = "Eurostat PRODCOM JSON-stat API is reachable."
    elif selected == "epa_echo":
        probe = partial(
            request_json,
            "EPA ECHO", f"{EPA_ECHO_BASE_URL}/echo_rest_services.get_facility_info",
            params={"output": "JSON", "p_fn": "NUCOR", "p_st": "AL"},
            timeout=60,
        )
        credential = ()
        detail = "EPA ECHO facility search API is reachable."
    else:
        def probe() -> object:
            return request_json(
                "USDA ERS",
                f"{USDA_ERS_BASE_URL}/year",
                params={"api_key": _ers_key()},
            )

        credential = ("USDA_ERS_API_KEY", "DATA_GOV_API_KEY")
        detail = "USDA ERS ARMS API is reachable."
    return checked_health_envelope(
        source=SOURCES[selected],
        credential_env=credential,
        probe=probe,
        success_detail=detail,
    )


@server.resource("environment-industry://overview", name="Environment and industry MCP overview")
def overview() -> str:
    """Describe official sources, credentials, and structured-data limits."""
    return json.dumps(
        {
            "sources": SOURCES,
            "credentials": {"usda_ers": ["USDA_ERS_API_KEY", "DATA_GOV_API_KEY"]},
            "routing": {
                "US energy": "existing eia MCP",
                "EU industrial production": "eurostat_prodcom",
                "US facility compliance": "epa_echo",
                "US farm finance": "usda_ers",
            },
            "document_policy": "Structured JSON/JSON-stat only; no PDF, spreadsheet, or OCR extraction.",
        },
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    server.run("stdio")
