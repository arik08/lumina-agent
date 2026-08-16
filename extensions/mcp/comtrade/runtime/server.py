"""UN Comtrade API MCP server."""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import threading
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


DEFAULT_API_HOST = "comtradeapi.un.org"
MAX_ROWS = 5000
MAX_REQUEST_ATTEMPTS = 4
MAX_RETRY_AFTER_SECONDS = 10.0
RETRY_AFTER_GRACE_SECONDS = 0.25
PUBLIC_REQUEST_INTERVAL_SECONDS = 2.25
TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}

logging.getLogger("httpx").setLevel(logging.WARNING)

server = FastMCP("comtrade")
_public_request_lock = threading.Lock()
_last_public_request_at = 0.0


def _httpx_verify_argument() -> bool | ssl.SSLContext:
    """Return the SSL verification config for UN Comtrade requests."""
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


def _env_value(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _api_key() -> str | None:
    return _env_value(
        "UN_COMTRADE_API_KEY",
        "COMTRADE_API_KEY",
        "UN_COMTRADE_SECONDARY_API_KEY",
        "COMTRADE_SECONDARY_API_KEY",
    )


def _api_base_url() -> str:
    override = _env_value("UN_COMTRADE_API_BASE_URL", "COMTRADE_API_BASE_URL")
    if override:
        return override.rstrip("/")
    protocol = (_env_value("UN_COMTRADE_API_PROTOCOL", "COMTRADE_API_PROTOCOL") or "https").lower()
    if protocol not in {"https", "http"}:
        raise ValueError("UN_COMTRADE_API_PROTOCOL must be 'https' or 'http'.")
    return f"{protocol}://{DEFAULT_API_HOST}"


def _request_headers(*, api_key: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": _env_value("UN_COMTRADE_API_USER_AGENT", "COMTRADE_API_USER_AGENT")
        or "Lumina UN Comtrade MCP/0.1",
    }
    if api_key:
        headers["Ocp-Apim-Subscription-Key"] = api_key
    return headers


def _retry_sleep(attempt: int, response: httpx.Response | None = None) -> None:
    delay = min(0.5 * attempt, 2.0)
    if response is not None and response.status_code == 429:
        try:
            retry_after = float(response.headers.get("Retry-After", ""))
        except ValueError:
            retry_after = 0.0
        if retry_after <= 0:
            try:
                message = str(response.json().get("message", ""))
            except (AttributeError, ValueError):
                message = ""
            match = re.search(
                r"(?:in|after)\s+(\d+(?:\.\d+)?)\s*seconds?", message, re.IGNORECASE
            )
            retry_after = float(match.group(1)) if match else 0.0
        if retry_after > 0:
            delay = max(delay, min(retry_after, MAX_RETRY_AFTER_SECONDS))
            delay += RETRY_AFTER_GRACE_SECONDS
    time.sleep(delay)


def _wait_for_request_slot() -> None:
    global _last_public_request_at
    with _public_request_lock:
        now = time.monotonic()
        delay = max(
            0.0,
            _last_public_request_at + PUBLIC_REQUEST_INTERVAL_SECONDS - now,
        )
        if delay > 0:
            time.sleep(delay)
        _last_public_request_at = now + delay


def _clean_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_ROWS))


def _safe_path_token(value: str, *, field_name: str) -> str:
    token = value.strip()
    if not token or not re.fullmatch(r"[A-Za-z0-9_,-]+", token):
        raise ValueError(f"{field_name} must contain only letters, numbers, '_', ',', or '-'.")
    return token


def _bool_param(value: bool) -> str:
    return "true" if value else "false"


def _partner_code_param(value: str) -> str | None:
    token = value.strip()
    if token.casefold() == "all":
        return None
    if not re.fullmatch(r"\d+(?:,\d+)*", token):
        raise ValueError(
            "partner_code must be 'all', '0' for World, or comma-separated numeric codes."
        )
    return token


def _to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _network_failure_message(base_url: str) -> str:
    return (
        "UN Comtrade API request failed. If this is a company network, check HTTPS proxy "
        "and corporate CA settings such as HTTPS_PROXY and SSL_CERT_FILE. "
        "Lumina will pass the configured corporate SSL context to httpx. "
        "If HTTPS inspection blocks this endpoint, set UN_COMTRADE_API_PROTOCOL=http "
        f"or UN_COMTRADE_API_BASE_URL to an approved proxy. Current base URL: {base_url}"
    )


def _request_json(path: str, params: dict[str, Any] | None = None, *, api_key: str | None = None) -> object:
    query = {key: value for key, value in (params or {}).items() if value is not None}
    url = f"{_api_base_url()}/{path.lstrip('/')}"
    last_error: BaseException | None = None
    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        try:
            if api_key is None:
                _wait_for_request_slot()
            response = httpx.get(
                url,
                params=query,
                timeout=45,
                verify=_httpx_verify_argument(),
                headers=_request_headers(api_key=api_key),
                follow_redirects=True,
            )
            if (
                getattr(response, "status_code", 200) in TRANSIENT_STATUS_CODES
                and attempt < MAX_REQUEST_ATTEMPTS
            ):
                _retry_sleep(attempt, response)
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
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code in TRANSIENT_STATUS_CODES and attempt < MAX_REQUEST_ATTEMPTS:
                _retry_sleep(attempt, exc.response)
                continue
            raise RuntimeError(_http_status_failure_message(exc.response)) from exc
    raise RuntimeError(_network_failure_message(_api_base_url())) from last_error


def _http_status_failure_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = {
            key: payload[key]
            for key in ("statusCode", "error", "message", "details")
            if key in payload
        }
        rendered = json.dumps(
            detail,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )[:1000]
    else:
        rendered = "No JSON error detail was returned."
    return f"UN Comtrade API returned HTTP {response.status_code}: {rendered}"


def _response_json(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError as exc:
        content_type = getattr(response, "headers", {}).get("content-type", "")
        snippet = getattr(response, "text", "")[:200].replace("\n", " ").strip()
        raise RuntimeError(
            "UN Comtrade API returned non-JSON content. This often means a company proxy, "
            "SSO gateway, or security appliance returned an HTML block page instead of API data. "
            f"status={getattr(response, 'status_code', 'unknown')} "
            f"content_type={content_type!r} snippet={snippet!r}"
        ) from exc


def _trade_path(prefix: str, type_code: str, freq_code: str, classification_code: str) -> str:
    safe_type = _safe_path_token(type_code, field_name="type_code")
    safe_freq = _safe_path_token(freq_code, field_name="freq_code")
    safe_classification = _safe_path_token(classification_code, field_name="classification_code")
    return f"{prefix}/{safe_type}/{safe_freq}/{safe_classification}"


def _trade_params(
    *,
    reporter_code: str,
    period: str,
    cmd_code: str,
    flow_code: str,
    partner_code: str,
    partner2_code: str,
    customs_code: str,
    mot_code: str,
    include_desc: bool,
) -> dict[str, Any]:
    return {
        "cmdCode": cmd_code,
        "flowCode": flow_code,
        "reporterCode": reporter_code,
        "period": period,
        "partnerCode": _partner_code_param(partner_code),
        "partner2Code": partner2_code,
        "customsCode": customs_code,
        "motCode": mot_code,
        "includeDesc": _bool_param(include_desc),
    }


def _limit_comtrade_payload(payload: object, limit: int) -> object:
    if not isinstance(payload, dict):
        return payload
    error = payload.get("error")
    if error:
        raise ValueError(f"UN Comtrade API error: {error}")
    data = payload.get("data")
    if isinstance(data, list):
        copied = dict(payload)
        copied["data"] = data[: _clean_limit(limit)]
        copied["returned"] = len(copied["data"])
        return copied
    return payload


def _csv_tokens(value: str) -> list[str]:
    return [token.strip() for token in value.split(",") if token.strip()]


def _trade_query_diagnostics(
    payload: object,
    *,
    reporter_code: str,
    period: str,
) -> object:
    """Add explicit reporter/period coverage so empty rows cannot be mistaken for an outage."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return payload

    requested_reporters = _csv_tokens(reporter_code)
    requested_periods = _csv_tokens(period)
    coverage: dict[str, set[str]] = {code: set() for code in requested_reporters}
    for row in payload["data"]:
        if not isinstance(row, dict):
            continue
        row_reporter = str(row.get("reporterCode", "")).strip()
        row_period = str(row.get("period", "")).strip()
        if row_reporter in coverage and row_period:
            coverage[row_reporter].add(row_period)

    missing_reporters = [code for code in requested_reporters if not coverage[code]]
    incomplete_reporters = [
        code
        for code in requested_reporters
        if coverage[code] and any(item not in coverage[code] for item in requested_periods)
    ]
    copied = dict(payload)
    copied["queryDiagnostics"] = {
        "requestedReporterCodes": requested_reporters,
        "requestedPeriods": requested_periods,
        "returnedPeriodsByReporter": {
            code: sorted(values) for code, values in coverage.items()
        },
        "missingReporterCodes": missing_reporters,
        "incompleteReporterCodes": incomplete_reporters,
        "complete": not missing_reporters and not incomplete_reporters,
    }
    warnings: list[str] = []
    if missing_reporters:
        warnings.append(
            "No rows were returned for reporter code(s) "
            + ", ".join(missing_reporters)
            + " under this exact query. This does not mean the MCP connection failed or that "
            "all requested reporters have no data. Check each reporter and use a common available period."
        )
    if incomplete_reporters:
        warnings.append(
            "Some requested periods are missing for reporter code(s) "
            + ", ".join(incomplete_reporters)
            + ". Do not compare reporters across different period coverage."
        )
    if warnings:
        copied["warnings"] = warnings
    return copied


def _reference_results(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("UN Comtrade reference endpoint returned an unexpected JSON shape.")
    return [row for row in payload["results"] if isinstance(row, dict)]


@server.tool()
def preview_trade_data(
    reporter_code: str,
    period: str,
    cmd_code: str = "TOTAL",
    flow_code: str = "X",
    partner_code: str = "0",
    type_code: str = "C",
    freq_code: str = "A",
    classification_code: str = "HS",
    partner2_code: str = "0",
    customs_code: str = "C00",
    mot_code: str = "0",
    include_desc: bool = True,
    limit: int = 100,
) -> str:
    """Fetch public preview trade data. Use partner_code="all" for a partner breakdown."""
    payload = _request_json(
        _trade_path("public/v1/preview", type_code, freq_code, classification_code),
        _trade_params(
            reporter_code=reporter_code,
            period=period,
            cmd_code=cmd_code,
            flow_code=flow_code,
            partner_code=partner_code,
            partner2_code=partner2_code,
            customs_code=customs_code,
            mot_code=mot_code,
            include_desc=include_desc,
        ),
    )
    diagnosed = _trade_query_diagnostics(payload, reporter_code=reporter_code, period=period)
    return _to_json(
        _limit_comtrade_payload(diagnosed, limit)
    )


@server.tool()
def get_trade_data(
    reporter_code: str,
    period: str,
    cmd_code: str = "TOTAL",
    flow_code: str = "X",
    partner_code: str = "0",
    type_code: str = "C",
    freq_code: str = "A",
    classification_code: str = "HS",
    partner2_code: str = "0",
    customs_code: str = "C00",
    mot_code: str = "0",
    include_desc: bool = True,
    limit: int = 1000,
) -> str:
    """Fetch keyed trade data. Use partner_code="all" for a partner breakdown."""
    api_key = _api_key()
    if not api_key:
        raise ValueError(
            "UN_COMTRADE_API_KEY is required for get_trade_data. "
            "Use preview_trade_data for keyless public preview access."
        )
    payload = _request_json(
        _trade_path("data/v1/get", type_code, freq_code, classification_code),
        _trade_params(
            reporter_code=reporter_code,
            period=period,
            cmd_code=cmd_code,
            flow_code=flow_code,
            partner_code=partner_code,
            partner2_code=partner2_code,
            customs_code=customs_code,
            mot_code=mot_code,
            include_desc=include_desc,
        ),
        api_key=api_key,
    )
    diagnosed = _trade_query_diagnostics(payload, reporter_code=reporter_code, period=period)
    return _to_json(
        _limit_comtrade_payload(diagnosed, limit)
    )


@server.tool()
def latest_common_annual_trade_data(
    reporter_codes: list[str],
    cmd_code: str = "TOTAL",
    flow_code: str = "M",
    partner_code: str = "0",
    latest_year: int | None = None,
    lookback_years: int = 5,
    type_code: str = "C",
    classification_code: str = "HS",
    partner2_code: str = "0",
    customs_code: str = "C00",
    mot_code: str = "0",
    include_desc: bool = True,
    limit: int = 1000,
) -> str:
    """Fetch the latest annual period that has rows for every requested reporter.

    Use this for cross-country comparisons where all reporters must share one period. The
    returned selectedPeriod is the newest common year found, not necessarily the latest
    calendar year.
    """
    api_key = _api_key()
    if not api_key:
        raise ValueError(
            "UN_COMTRADE_API_KEY is required for latest_common_annual_trade_data."
        )
    cleaned_reporters = list(
        dict.fromkeys(str(code).strip() for code in reporter_codes if str(code).strip())
    )
    if len(cleaned_reporters) < 2:
        raise ValueError("reporter_codes must contain at least two reporter codes.")
    if any(not code.isdigit() for code in cleaned_reporters):
        raise ValueError("reporter_codes must contain numeric UN Comtrade reporter codes.")
    years_to_check = max(1, min(int(lookback_years), 10))
    start_year = int(latest_year) if latest_year is not None else datetime.now(UTC).year - 1
    reporter_csv = ",".join(cleaned_reporters)
    path = _trade_path("data/v1/get", type_code, "A", classification_code)
    attempted_periods: list[str] = []

    for year in range(start_year, start_year - years_to_check, -1):
        period = str(year)
        attempted_periods.append(period)
        params = _trade_params(
            reporter_code=reporter_csv,
            period=period,
            cmd_code=cmd_code,
            flow_code=flow_code,
            partner_code=partner_code,
            partner2_code=partner2_code,
            customs_code=customs_code,
            mot_code=mot_code,
            include_desc=include_desc,
        )
        payload = _limit_comtrade_payload(
            _trade_query_diagnostics(
                _request_json(path, params, api_key=api_key),
                reporter_code=reporter_csv,
                period=period,
            ),
            limit,
        )
        if not isinstance(payload, dict):
            continue
        diagnostics = payload.get("queryDiagnostics")
        if not isinstance(diagnostics, dict) or not diagnostics.get("complete"):
            continue
        copied = dict(payload)
        copied["selectedPeriod"] = period
        copied["attemptedPeriods"] = attempted_periods
        copied["selectionReason"] = (
            "Latest annual period with data for every requested reporter under the exact query."
        )
        return _to_json(copied)

    return _to_json(
        {
            "count": 0,
            "data": [],
            "selectedPeriod": None,
            "attemptedPeriods": attempted_periods,
            "queryDiagnostics": {
                "requestedReporterCodes": cleaned_reporters,
                "complete": False,
            },
            "warnings": [
                "No common annual period was found for every requested reporter. "
                "Do not construct a cross-country comparison from mixed periods."
            ],
        }
    )


@server.tool()
def list_reporters(limit: int = 300) -> str:
    """List UN Comtrade reporter areas and ISO codes."""
    rows = _reference_results(_request_json("files/v1/app/reference/Reporters.json"))
    return _to_json(rows[: _clean_limit(limit)])


@server.tool()
def search_reporters(keyword: str, limit: int = 50) -> str:
    """Search UN Comtrade reporter areas by name, numeric code, or ISO code."""
    needle = keyword.casefold().strip()
    if not needle:
        raise ValueError("keyword is required.")
    rows = _reference_results(_request_json("files/v1/app/reference/Reporters.json"))
    matches = [
        row
        for row in rows
        if needle
        in " ".join(
            str(row.get(key, ""))
            for key in (
                "reporterCode",
                "reporterDesc",
                "reporterNote",
                "reporterCodeIsoAlpha2",
                "reporterCodeIsoAlpha3",
            )
        ).casefold()
    ]
    return _to_json(matches[: _clean_limit(limit)])


@server.tool()
def check_connection() -> str:
    """Check whether UN Comtrade public preview API is reachable from the current network."""
    payload = _request_json(
        "public/v1/preview/C/A/HS",
        {
            "cmdCode": "TOTAL",
            "flowCode": "X",
            "reporterCode": "410",
            "period": "2023",
            "partnerCode": "0",
            "includeDesc": "true",
        },
    )
    count = payload.get("count") if isinstance(payload, dict) else None
    return _to_json(
        {
            "ok": True,
            "base_url": _api_base_url(),
            "preview_count": count,
            "api_key_configured": bool(_api_key()),
            "proxy_env_present": {
                "HTTP_PROXY": bool(os.environ.get("HTTP_PROXY")),
                "HTTPS_PROXY": bool(os.environ.get("HTTPS_PROXY")),
                "SSL_CERT_FILE": bool(os.environ.get("SSL_CERT_FILE")),
                "REQUESTS_CA_BUNDLE": bool(os.environ.get("REQUESTS_CA_BUNDLE")),
                "UN_COMTRADE_API_PROTOCOL": bool(
                    _env_value("UN_COMTRADE_API_PROTOCOL", "COMTRADE_API_PROTOCOL")
                ),
                "UN_COMTRADE_API_BASE_URL": bool(
                    _env_value("UN_COMTRADE_API_BASE_URL", "COMTRADE_API_BASE_URL")
                ),
            },
            "message": "UN Comtrade public preview API is reachable.",
        }
    )


@server.resource("comtrade://overview", name="UN Comtrade API MCP overview")
def overview() -> str:
    """Describe available UN Comtrade tools, codes, and company-network settings."""
    return _to_json(
        {
            "service": "UN Comtrade API",
            "base_url": _api_base_url(),
            "tools": [
                "preview_trade_data",
                "get_trade_data",
                "latest_common_annual_trade_data",
                "list_reporters",
                "search_reporters",
                "check_connection",
            ],
            "common_codes": {
                "type_code": {"C": "commodities/goods", "S": "services"},
                "freq_code": {"A": "annual", "M": "monthly"},
                "classification_code": {"HS": "Harmonized System", "SITC": "SITC"},
                "flow_code": {"M": "import", "X": "export"},
                "partner_code": {"0": "World"},
                "cmd_code": {"TOTAL": "All commodities"},
            },
            "authentication": [
                "preview_trade_data uses public/v1/preview and does not require a key.",
                "get_trade_data uses data/v1/get and requires UN_COMTRADE_API_KEY or COMTRADE_API_KEY.",
                "latest_common_annual_trade_data finds one annual period shared by every reporter.",
            ],
            "company_network_notes": [
                "Corporate SSL bundles are passed to httpx through Lumina certificate support.",
                "Set UN_COMTRADE_API_PROTOCOL=http if HTTPS inspection blocks comtradeapi.un.org.",
                "Set UN_COMTRADE_API_BASE_URL to an approved proxy or mirror if required.",
            ],
        }
    )


if __name__ == "__main__":
    server.run("stdio")
