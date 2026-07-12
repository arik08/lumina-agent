"""U.S. EIA Open Data API MCP server."""

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


DEFAULT_API_HOST = "api.eia.gov/v2"
MAX_ROWS = 5000
MAX_REQUEST_ATTEMPTS = 3
TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}

ENERGY_PRICE_SERIES = {
    "wti": "PET.RWTC.D",
    "brent": "PET.RBRTE.D",
    "henry_hub": "NG.RNGWHHD.D",
    "gasoline_regular": "PET.EMM_EPMR_PTE_NUS_DPG.W",
    "diesel": "PET.EMD_EPD2D_PTE_NUS_DPG.W",
}

logging.getLogger("httpx").setLevel(logging.WARNING)

server = FastMCP("eia")


def _httpx_verify_argument() -> bool | ssl.SSLContext:
    """Return the SSL verification config for EIA requests."""
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
    key = _env_value("EIA_API_KEY")
    if not key:
        raise ValueError("EIA_API_KEY is required for the EIA MCP.")
    return key


def _api_base_url() -> str:
    override = _env_value("EIA_API_BASE_URL")
    if override:
        return override.rstrip("/")
    protocol = (_env_value("EIA_API_PROTOCOL") or "https").lower()
    if protocol not in {"https", "http"}:
        raise ValueError("EIA_API_PROTOCOL must be 'https' or 'http'.")
    return f"{protocol}://{DEFAULT_API_HOST}"


def _to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _clean_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_ROWS))


def _retry_sleep(attempt: int) -> None:
    time.sleep(min(0.25 * attempt, 1.0))


def _safe_series_id(series_id: str) -> str:
    token = series_id.strip()
    if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+", token):
        raise ValueError("series_id must contain only letters, numbers, '.', '_', or '-'.")
    return token


def _request_json(path: str, params: dict[str, Any] | None = None) -> object:
    query = {"api_key": _api_key()}
    query.update({key: value for key, value in (params or {}).items() if value is not None})
    url = f"{_api_base_url()}/{path.lstrip('/')}"
    last_error: BaseException | None = None
    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        try:
            response = httpx.get(
                url,
                params=query,
                timeout=45,
                verify=_httpx_verify_argument(),
                headers={"Accept": "application/json", "User-Agent": "MyHarness EIA MCP/0.1"},
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
        "EIA API request failed. Check company proxy, HTTPS_PROXY, SSL_CERT_FILE, "
        f"or EIA_API_PROTOCOL=http. Current base URL: {_api_base_url()}"
    ) from last_error


def _response_json(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError as exc:
        snippet = getattr(response, "text", "")[:200].replace("\n", " ").strip()
        raise RuntimeError(
            "EIA API returned non-JSON content. A company proxy or SSO gateway may have "
            f"returned HTML instead. snippet={snippet!r}"
        ) from exc


def _extract_response_data(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("EIA API returned an unexpected JSON shape.")
    response = payload.get("response")
    if not isinstance(response, dict):
        raise ValueError("EIA API response does not contain response.")
    data = response.get("data", [])
    if not isinstance(data, list):
        raise ValueError("EIA API response.data is not a list.")
    return [row for row in data if isinstance(row, dict)]


@server.tool()
def get_series(
    series_id: str,
    start: str | None = None,
    end: str | None = None,
    length: int = 100,
) -> str:
    """Fetch EIA seriesid data such as PET.RWTC.D or NG.RNGWHHD.D."""
    safe_series = _safe_series_id(series_id)
    rows = _extract_response_data(
        _request_json(
            f"seriesid/{safe_series}",
            {
                "start": start,
                "end": end,
                "length": _clean_limit(length),
            },
        )
    )
    return _to_json(rows[: _clean_limit(length)])


@server.tool()
def get_energy_price(alias: str, start: str | None = None, end: str | None = None, length: int = 100) -> str:
    """Fetch common energy price series by alias: wti, brent, henry_hub, gasoline_regular, diesel."""
    series_id = ENERGY_PRICE_SERIES.get(alias.lower())
    if not series_id:
        raise ValueError(f"Unknown alias: {alias}. Known aliases: {', '.join(sorted(ENERGY_PRICE_SERIES))}")
    return get_series(series_id, start=start, end=end, length=length)


@server.tool()
def list_price_series() -> str:
    """List built-in EIA energy price aliases and series IDs."""
    return _to_json(ENERGY_PRICE_SERIES)


@server.tool()
def check_connection() -> str:
    """Check whether EIA is reachable and the configured API key works."""
    rows = json.loads(get_energy_price("wti", length=1))
    return _to_json(
        {
            "ok": True,
            "base_url": _api_base_url(),
            "sample_count": len(rows),
            "message": "EIA API is reachable.",
        }
    )


@server.resource("eia://overview", name="EIA Open Data MCP overview")
def overview() -> str:
    """Describe available EIA MCP tools and common price aliases."""
    return _to_json(
        {
            "service": "U.S. Energy Information Administration Open Data API",
            "tools": ["get_series", "get_energy_price", "list_price_series", "check_connection"],
            "price_series": ENERGY_PRICE_SERIES,
            "company_network_notes": [
                "Corporate SSL bundles are passed to httpx through MyHarness certificate support.",
                "Set EIA_API_PROTOCOL=http or EIA_API_BASE_URL if company HTTPS inspection requires it.",
            ],
        }
    )


if __name__ == "__main__":
    server.run("stdio")
