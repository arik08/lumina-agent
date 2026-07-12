"""Bank of Korea ECOS Open API MCP server."""

from __future__ import annotations

import json
import logging
import os
import ssl
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


DEFAULT_API_HOST = "ecos.bok.or.kr/api"
MAX_ROWS = 1000
MAX_REQUEST_ATTEMPTS = 3
TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}

EXCHANGE_RATE_ITEMS = {
    "USD": "0000001",
    "JPY100": "0000002",
    "EUR": "0000003",
    "CNY": "0000053",
}

logging.getLogger("httpx").setLevel(logging.WARNING)

server = FastMCP("ecos")


def _httpx_verify_argument() -> bool | ssl.SSLContext:
    """Return the SSL verification config for ECOS requests."""
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


def _env_value(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _api_key() -> str:
    key = _env_value("ECOS_API_KEY", "BOK_ECOS_API_KEY")
    if not key:
        raise ValueError("ECOS_API_KEY is required for the Bank of Korea ECOS MCP.")
    return key


def _api_base_url() -> str:
    override = _env_value("ECOS_API_BASE_URL", "BOK_ECOS_API_BASE_URL")
    if override:
        return override.rstrip("/")
    protocol = (_env_value("ECOS_API_PROTOCOL", "BOK_ECOS_API_PROTOCOL") or "https").lower()
    if protocol not in {"https", "http"}:
        raise ValueError("ECOS_API_PROTOCOL must be 'https' or 'http'.")
    return f"{protocol}://{DEFAULT_API_HOST}"


def _to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _clean_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_ROWS))


def _retry_sleep(attempt: int) -> None:
    time.sleep(min(0.25 * attempt, 1.0))


def _request_json(path: str) -> object:
    url = f"{_api_base_url()}/{path.strip('/')}"
    last_error: BaseException | None = None
    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        try:
            response = httpx.get(
                url,
                timeout=30,
                verify=_httpx_verify_argument(),
                headers={"Accept": "application/json", "User-Agent": "MyHarness ECOS MCP/0.1"},
                follow_redirects=True,
            )
            if (
                getattr(response, "status_code", 200) in TRANSIENT_STATUS_CODES
                and attempt < MAX_REQUEST_ATTEMPTS
            ):
                _retry_sleep(attempt)
                continue
            response.raise_for_status()
            return _response_json(response)
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
            if exc.response.status_code in TRANSIENT_STATUS_CODES and attempt < MAX_REQUEST_ATTEMPTS:
                _retry_sleep(attempt)
                continue
            break
    raise RuntimeError(
        "ECOS API request failed. Check company proxy, HTTPS_PROXY, SSL_CERT_FILE, "
        f"or ECOS_API_PROTOCOL=http. Current base URL: {_api_base_url()}"
    ) from last_error


def _response_json(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError as exc:
        snippet = getattr(response, "text", "")[:200].replace("\n", " ").strip()
        raise RuntimeError(
            "ECOS API returned non-JSON content. A company proxy or SSO gateway may have "
            f"returned HTML instead. snippet={snippet!r}"
        ) from exc


def _extract_rows(payload: object, root_name: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("ECOS API returned an unexpected JSON shape.")
    root = payload.get(root_name)
    if not isinstance(root, dict):
        result = payload.get("RESULT")
        if isinstance(result, dict):
            raise ValueError(f"ECOS API error {result.get('CODE')}: {result.get('MESSAGE')}")
        raise ValueError(f"ECOS API response does not contain {root_name}.")
    rows = root.get("row", [])
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError(f"ECOS API {root_name}.row is not a list.")
    return [row for row in rows if isinstance(row, dict)]


@server.tool()
def get_exchange_rate(
    currency: str = "USD",
    start_date: str = "20240101",
    end_date: str = "20241231",
    limit: int = 1000,
) -> str:
    """Fetch ECOS daily KRW exchange rates for USD, JPY100, EUR, or CNY."""
    item_code = EXCHANGE_RATE_ITEMS.get(currency.upper(), currency)
    return get_statistic_data(
        stat_code="731Y001",
        cycle="D",
        start=start_date,
        end=end_date,
        item_code1=item_code,
        limit=limit,
    )


@server.tool()
def get_statistic_data(
    stat_code: str,
    cycle: str,
    start: str,
    end: str,
    item_code1: str | None = None,
    item_code2: str | None = None,
    item_code3: str | None = None,
    item_code4: str | None = None,
    limit: int = 1000,
) -> str:
    """Fetch generic ECOS StatisticSearch rows by table code, cycle, date range, and optional item codes."""
    safe_limit = _clean_limit(limit)
    parts = [
        "StatisticSearch",
        _api_key(),
        "json",
        "kr",
        "1",
        str(safe_limit),
        stat_code,
        cycle,
        start,
        end,
    ]
    parts.extend(code for code in (item_code1, item_code2, item_code3, item_code4) if code)
    payload = _request_json("/".join(parts))
    return _to_json(_extract_rows(payload, "StatisticSearch"))


@server.tool()
def get_key_statistics(limit: int = 100) -> str:
    """Return ECOS key statistics, including recent KRW exchange-rate headline values."""
    safe_limit = _clean_limit(limit)
    payload = _request_json(f"KeyStatisticList/{_api_key()}/json/kr/1/{safe_limit}")
    return _to_json(_extract_rows(payload, "KeyStatisticList"))


@server.tool()
def list_stat_tables(limit: int = 1000) -> str:
    """List ECOS statistic tables and codes."""
    safe_limit = _clean_limit(limit)
    payload = _request_json(f"StatisticTableList/{_api_key()}/json/kr/1/{safe_limit}")
    return _to_json(_extract_rows(payload, "StatisticTableList"))


@server.tool()
def list_stat_items(stat_code: str, limit: int = 1000) -> str:
    """List ECOS item codes for one statistic table."""
    safe_limit = _clean_limit(limit)
    payload = _request_json(f"StatisticItemList/{_api_key()}/json/kr/1/{safe_limit}/{stat_code}")
    return _to_json(_extract_rows(payload, "StatisticItemList"))


@server.tool()
def check_connection() -> str:
    """Check whether ECOS is reachable and the configured API key works."""
    rows = json.loads(get_exchange_rate("USD", "20240501", "20240503", limit=10))
    return _to_json(
        {
            "ok": True,
            "base_url": _api_base_url(),
            "sample_count": len(rows),
            "message": "ECOS API is reachable.",
        }
    )


@server.resource("ecos://overview", name="Bank of Korea ECOS MCP overview")
def overview() -> str:
    """Describe available ECOS MCP tools and common exchange-rate codes."""
    return _to_json(
        {
            "service": "Bank of Korea ECOS Open API",
            "tools": [
                "get_exchange_rate",
                "get_statistic_data",
                "get_key_statistics",
                "list_stat_tables",
                "list_stat_items",
                "check_connection",
            ],
            "exchange_rate_table": "731Y001",
            "exchange_rate_items": EXCHANGE_RATE_ITEMS,
            "company_network_notes": [
                "Corporate SSL bundles are passed to httpx through MyHarness certificate support.",
                "Set ECOS_API_PROTOCOL=http or ECOS_API_BASE_URL if company HTTPS inspection requires it.",
            ],
        }
    )


if __name__ == "__main__":
    server.run("stdio")
