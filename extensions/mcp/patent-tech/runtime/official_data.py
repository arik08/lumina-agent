"""Shared helpers for official public-data MCP adapters."""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import time
from datetime import UTC, datetime
from collections.abc import Callable
from typing import Any

import httpx


TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
MAX_REQUEST_ATTEMPTS = 3

# httpx logs the fully rendered request URL at INFO level. Several official APIs
# put credentials in the query string, so allowing that log would disclose keys.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def first_env(*names: str) -> str | None:
    """Return the first non-empty environment variable in ``names``."""
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def httpx_verify_argument() -> bool | ssl.SSLContext:
    """Return the Lumina-provided TLS bundle configuration."""
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

def clean_limit(limit: int, *, maximum: int = 1000) -> int:
    """Clamp a caller-provided row limit to a safe positive range."""
    return max(1, min(int(limit), maximum))


def safe_identifier(
    value: str,
    *,
    field_name: str,
    pattern: str = r"[A-Za-z0-9_.:-]+",
) -> str:
    """Validate identifiers before interpolating them into URL paths."""
    token = value.strip()
    if not token or not re.fullmatch(pattern, token):
        raise ValueError(f"{field_name} has an invalid format.")
    return token


def request(
    source: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 45,
) -> httpx.Response:
    """Issue a retrying GET without leaking query parameters in raised messages."""
    last_error: BaseException | None = None
    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        try:
            response = httpx.get(
                url,
                params={key: value for key, value in (params or {}).items() if value is not None},
                headers=headers,
                timeout=timeout,
                verify=httpx_verify_argument(),
                follow_redirects=True,
            )
            if response.status_code in TRANSIENT_STATUS_CODES and attempt < MAX_REQUEST_ATTEMPTS:
                time.sleep(min(0.25 * attempt, 1.0))
                continue
            response.raise_for_status()
            return response
        except (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.HTTPStatusError,
            httpx.ProxyError,
            httpx.ReadError,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
            OSError,
            ssl.SSLError,
        ) as exc:
            last_error = exc
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            retryable = not isinstance(exc, httpx.HTTPStatusError) or status in TRANSIENT_STATUS_CODES
            if not retryable or attempt == MAX_REQUEST_ATTEMPTS:
                break
            time.sleep(min(0.25 * attempt, 1.0))
    raise RuntimeError(
        f"{source} request failed. Check the credential, service status, corporate proxy, "
        "HTTPS_PROXY, and SSL_CERT_FILE settings."
    ) from last_error


def request_json(
    source: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 45,
) -> object:
    """Fetch a JSON response and emit a bounded content diagnostic on parse failure."""
    response = request(source, url, params=params, headers=headers, timeout=timeout)
    try:
        return response.json()
    except ValueError as exc:
        content_type = response.headers.get("content-type", "")
        raise RuntimeError(
            f"{source} returned non-JSON content. content_type={content_type!r} "
            f"response_bytes={len(response.content)}"
        ) from exc


def post_form_json(
    source: str,
    url: str,
    *,
    data: dict[str, Any],
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = 45,
) -> object:
    """POST a small form with bounded retries and secret-safe errors."""
    last_error: BaseException | None = None
    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        try:
            response = httpx.post(
                url,
                data=data,
                headers=headers,
                auth=auth,
                timeout=timeout,
                verify=httpx_verify_argument(),
                follow_redirects=True,
            )
            if response.status_code in TRANSIENT_STATUS_CODES and attempt < MAX_REQUEST_ATTEMPTS:
                time.sleep(min(0.25 * attempt, 1.0))
                continue
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError, OSError, ssl.SSLError) as exc:
            last_error = exc
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            retryable = not isinstance(exc, httpx.HTTPStatusError) or status in TRANSIENT_STATUS_CODES
            if not retryable or attempt == MAX_REQUEST_ATTEMPTS:
                break
            time.sleep(min(0.25 * attempt, 1.0))
    raise RuntimeError(
        f"{source} authentication request failed. Check the credential, service status, "
        "corporate proxy, HTTPS_PROXY, and SSL_CERT_FILE settings."
    ) from last_error


def result_envelope(
    *,
    source: str,
    source_id: str,
    data: object,
    as_of: str | None = None,
    unit: str | None = None,
    revision: str | None = None,
    completeness: str = "reported_by_source",
    license_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Return the common provenance envelope required by official-data MCPs."""
    payload: dict[str, Any] = {
        "source": source,
        "source_id": source_id,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "as_of": as_of,
        "unit": unit,
        "revision": revision,
        "completeness": completeness,
        "license": license_name,
        "data": data,
    }
    if metadata:
        payload["metadata"] = metadata
    return json.dumps(payload, ensure_ascii=False, indent=2)


def health_envelope(
    *,
    source: str,
    ok: bool,
    credential_env: tuple[str, ...] = (),
    detail: str,
) -> str:
    """Return connection state while exposing only credential presence, never values."""
    return json.dumps(
        {
            "source": source,
            "ok": ok,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "credential": {
                "required": bool(credential_env),
                "configured": any(bool(os.environ.get(name)) for name in credential_env),
                "environment_names": list(credential_env),
            },
            "detail": detail,
        },
        ensure_ascii=False,
        indent=2,
    )


def checked_health_envelope(
    *,
    source: str,
    probe: Callable[[], object],
    success_detail: str,
    credential_env: tuple[str, ...] = (),
    missing_detail: str = "Official API adapter is installed but its credential is not configured.",
) -> str:
    """Run one health probe and always return a secret-safe health envelope."""
    if credential_env and not first_env(*credential_env):
        return health_envelope(
            source=source,
            ok=False,
            credential_env=credential_env,
            detail=missing_detail,
        )
    try:
        probe()
    except Exception as exc:  # health tools must report failures instead of crashing
        return health_envelope(
            source=source,
            ok=False,
            credential_env=credential_env,
            detail=f"Official endpoint probe failed ({type(exc).__name__}).",
        )
    return health_envelope(
        source=source,
        ok=True,
        credential_env=credential_env,
        detail=success_detail,
    )
