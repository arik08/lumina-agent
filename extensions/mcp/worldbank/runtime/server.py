"""World Bank v2 API MCP server."""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


DEFAULT_API_HOST = "api.worldbank.org/v2"
MAX_ROWS = 5000
MAX_PER_PAGE = 1000
MAX_REQUEST_ATTEMPTS = 3
DEFAULT_SOURCE_ID = 2
TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}

logging.getLogger("httpx").setLevel(logging.WARNING)

server = FastMCP("worldbank")


def _httpx_verify_argument() -> bool | ssl.SSLContext:
    """Return the SSL verification config for World Bank API requests."""
    try:
        from myharness.utils.certificates import httpx_verify_argument
    except ImportError:
        bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
        if not bundle:
            return True
        context = ssl.create_default_context()
        try:
            context.set_ciphers("DEFAULT@SECLEVEL=1")
        except ssl.SSLError:
            pass
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        context.load_verify_locations(cafile=bundle)
        return context
    return httpx_verify_argument()


def _clean_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_ROWS))


def _env_value(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _api_base_url() -> str:
    """Return the World Bank API base URL, allowing company-network overrides."""
    override = _env_value("WORLD_BANK_API_BASE_URL", "WORLDBANK_API_BASE_URL")
    if override:
        return override.rstrip("/")
    protocol = (_env_value("WORLD_BANK_API_PROTOCOL", "WORLDBANK_API_PROTOCOL") or "https").lower()
    if protocol not in {"https", "http"}:
        raise ValueError("WORLD_BANK_API_PROTOCOL must be 'https' or 'http'.")
    return f"{protocol}://{DEFAULT_API_HOST}"


def _request_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": _env_value("WORLD_BANK_API_USER_AGENT", "WORLDBANK_API_USER_AGENT")
        or "MyHarness WorldBank MCP/0.1",
    }


def _retry_sleep(attempt: int) -> None:
    time.sleep(min(0.25 * attempt, 1.0))


def _safe_path_token(value: str, *, field_name: str) -> str:
    token = value.strip()
    if not token or not re.fullmatch(r"[A-Za-z0-9_.;-]+", token):
        raise ValueError(f"{field_name} must contain only letters, numbers, '.', '_', ';', or '-'.")
    return token


def _to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _error_message(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    messages = payload.get("message")
    if not isinstance(messages, list):
        return None
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        message_id = message.get("id")
        value = message.get("value")
        if message_id and value:
            parts.append(f"{message_id}: {value}")
        elif value:
            parts.append(str(value))
    return "; ".join(parts) if parts else None


def _parse_worldbank_payload(payload: object) -> tuple[dict[str, Any], list[Any]]:
    error = _error_message(payload)
    if error:
        raise ValueError(f"World Bank API error: {error}")
    if not isinstance(payload, list) or len(payload) < 2:
        raise ValueError("World Bank API returned an unexpected JSON shape.")
    metadata = payload[0] if isinstance(payload[0], dict) else {}
    rows = payload[1]
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ValueError("World Bank API returned non-list data rows.")
    return metadata, rows


def _network_failure_message(base_url: str) -> str:
    return (
        "World Bank API request failed. If this is a company network, check HTTPS proxy "
        "and corporate CA settings such as HTTPS_PROXY and SSL_CERT_FILE. "
        "MyHarness will pass the configured corporate SSL context to httpx. "
        "If HTTPS inspection blocks this endpoint, set WORLD_BANK_API_PROTOCOL=http "
        f"or WORLD_BANK_API_BASE_URL to an approved proxy. Current base URL: {base_url}"
    )


def _request_page(url: str, query: dict[str, Any]) -> httpx.Response:
    last_error: BaseException | None = None
    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        try:
            response = httpx.get(
                url,
                params=query,
                timeout=30,
                verify=_httpx_verify_argument(),
                headers=_request_headers(),
                follow_redirects=True,
            )
            if (
                getattr(response, "status_code", 200) in TRANSIENT_STATUS_CODES
                and attempt < MAX_REQUEST_ATTEMPTS
            ):
                _retry_sleep(attempt)
                continue
            response.raise_for_status()
            return response
        except (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ProxyError,
            httpx.ReadError,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
            OSError,
            ssl.SSLError,
        ) as exc:
            last_error = exc
            if attempt < MAX_REQUEST_ATTEMPTS:
                _retry_sleep(attempt)
                continue
            break
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code in TRANSIENT_STATUS_CODES and attempt < MAX_REQUEST_ATTEMPTS:
                _retry_sleep(attempt)
                continue
            break
    raise RuntimeError(_network_failure_message(_api_base_url())) from last_error


def _response_json(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError as exc:
        content_type = getattr(response, "headers", {}).get("content-type", "")
        snippet = getattr(response, "text", "")[:200].replace("\n", " ").strip()
        raise RuntimeError(
            "World Bank API returned non-JSON content. This often means a company proxy, "
            "SSO gateway, or security appliance returned an HTML block page instead of API data. "
            f"status={getattr(response, 'status_code', 'unknown')} "
            f"content_type={content_type!r} snippet={snippet!r}"
        ) from exc


def _get_page(path: str, params: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    query = {"format": "json"}
    query.update({key: value for key, value in params.items() if value is not None})
    response = _request_page(f"{_api_base_url()}/{path.lstrip('/')}", query)
    return _parse_worldbank_payload(_response_json(response))


def _fetch_rows(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    limit: int = 100,
    fetch_all: bool = False,
) -> list[Any]:
    safe_limit = _clean_limit(limit)
    query = dict(params or {})
    query["per_page"] = min(safe_limit, MAX_PER_PAGE)
    rows: list[Any] = []
    page = 1
    while True:
        query["page"] = page
        metadata, page_rows = _get_page(path, query)
        rows.extend(page_rows)
        pages = int(metadata.get("pages") or 1)
        if not fetch_all or page >= pages or len(rows) >= safe_limit:
            break
        page += 1
    return rows[:safe_limit]


@server.tool()
def list_countries(
    region: str | None = None,
    income_level: str | None = None,
    lending_type: str | None = None,
    limit: int = 300,
) -> str:
    """List World Bank countries and economies, optionally filtered by region, income level, or lending type code."""
    rows = _fetch_rows(
        "country",
        {
            "region": region,
            "incomeLevel": income_level,
            "lendingType": lending_type,
        },
        limit=limit,
        fetch_all=True,
    )
    return _to_json(rows)


@server.tool()
def search_countries(keyword: str, limit: int = 50) -> str:
    """Search World Bank country/economy metadata by name, ISO code, capital city, region, or income group."""
    needle = keyword.casefold().strip()
    if not needle:
        raise ValueError("keyword is required.")
    rows = _fetch_rows("country", limit=300, fetch_all=True)
    matches = [
        row
        for row in rows
        if isinstance(row, dict)
        and needle
        in " ".join(
            str(value)
            for value in [
                row.get("id"),
                row.get("iso2Code"),
                row.get("name"),
                row.get("capitalCity"),
                (row.get("region") or {}).get("value") if isinstance(row.get("region"), dict) else "",
                (row.get("incomeLevel") or {}).get("value")
                if isinstance(row.get("incomeLevel"), dict)
                else "",
            ]
        ).casefold()
    ]
    return _to_json(matches[: _clean_limit(limit)])


@server.tool()
def search_indicators(keyword: str, source_id: int = DEFAULT_SOURCE_ID, limit: int = 50) -> str:
    """Search World Bank indicators by ID, name, or source note. Source 2 is World Development Indicators."""
    needle = keyword.casefold().strip()
    if not needle:
        raise ValueError("keyword is required.")
    rows = _fetch_rows(f"sources/{int(source_id)}/indicators", limit=MAX_ROWS, fetch_all=True)
    matches = [
        row
        for row in rows
        if isinstance(row, dict)
        and needle
        in " ".join(
            str(row.get(key, "")) for key in ("id", "name", "sourceNote", "sourceOrganization")
        ).casefold()
    ]
    return _to_json(matches[: _clean_limit(limit)])


@server.tool()
def get_indicator_metadata(indicator: str, source_id: int | None = None, limit: int = 20) -> str:
    """Return World Bank metadata for one indicator ID such as NY.GDP.MKTP.CD."""
    indicator_id = _safe_path_token(indicator, field_name="indicator")
    if source_id is None:
        path = f"indicator/{indicator_id}"
    else:
        path = f"sources/{int(source_id)}/indicators/{indicator_id}"
    rows = _fetch_rows(path, limit=limit, fetch_all=True)
    return _to_json(rows)


@server.tool()
def fetch_indicator_data(
    country: str,
    indicator: str,
    start_year: int | None = None,
    end_year: int | None = None,
    frequency: str | None = None,
    source_id: int | None = DEFAULT_SOURCE_ID,
    limit: int = 200,
) -> str:
    """Fetch World Bank time-series data for one country/economy and indicator."""
    country_id = _safe_path_token(country, field_name="country")
    indicator_id = _safe_path_token(indicator, field_name="indicator")
    date = None
    if start_year is not None and end_year is not None:
        date = f"{int(start_year)}:{int(end_year)}"
    elif start_year is not None:
        date = str(int(start_year))
    elif end_year is not None:
        date = str(int(end_year))
    rows = _fetch_rows(
        f"country/{country_id}/indicator/{indicator_id}",
        {
            "date": date,
            "frequency": frequency,
            "source": source_id,
        },
        limit=limit,
        fetch_all=True,
    )
    return _to_json(rows)


@server.tool()
def check_connection() -> str:
    """Check whether the World Bank API is reachable from the current network."""
    rows = _fetch_rows("country/KOR/indicator/SP.POP.TOTL", {"date": "2022:2023"}, limit=2, fetch_all=True)
    return _to_json(
        {
            "ok": True,
            "base_url": _api_base_url(),
            "sample_count": len(rows),
            "proxy_env_present": {
                "HTTP_PROXY": bool(os.environ.get("HTTP_PROXY")),
                "HTTPS_PROXY": bool(os.environ.get("HTTPS_PROXY")),
                "SSL_CERT_FILE": bool(os.environ.get("SSL_CERT_FILE")),
                "REQUESTS_CA_BUNDLE": bool(os.environ.get("REQUESTS_CA_BUNDLE")),
                "WORLD_BANK_API_PROTOCOL": bool(
                    _env_value("WORLD_BANK_API_PROTOCOL", "WORLDBANK_API_PROTOCOL")
                ),
                "WORLD_BANK_API_BASE_URL": bool(
                    _env_value("WORLD_BANK_API_BASE_URL", "WORLDBANK_API_BASE_URL")
                ),
            },
            "message": "World Bank API is reachable.",
        }
    )


@server.resource("worldbank://overview", name="World Bank API MCP overview")
def overview() -> str:
    """Describe available World Bank tools and common indicator examples."""
    return _to_json(
        {
            "service": "World Bank v2 API",
            "base_url": _api_base_url(),
            "default_source_id": DEFAULT_SOURCE_ID,
            "tools": [
                "list_countries",
                "search_countries",
                "search_indicators",
                "get_indicator_metadata",
                "fetch_indicator_data",
                "check_connection",
            ],
            "examples": {
                "GDP current US$": "NY.GDP.MKTP.CD",
                "Population total": "SP.POP.TOTL",
                "Inflation consumer prices": "FP.CPI.TOTL.ZG",
                "Manufacturing value added current US$": "NV.IND.MANF.CD",
            },
            "notes": [
                "Use semicolon-separated country codes such as KOR;USA for multiple economies.",
                "Use country=all for all countries when the requested result size is reasonable.",
                "Source 2 is World Development Indicators.",
                "For company networks, set WORLD_BANK_API_PROTOCOL=http or WORLD_BANK_API_BASE_URL when HTTPS inspection blocks api.worldbank.org.",
            ],
        }
    )


if __name__ == "__main__":
    server.run("stdio")
