from __future__ import annotations

from urllib.parse import urlsplit

from .errors import ProviderConfigurationError, ProviderRequestError


def validate_http_base_url(value: str, provider_label: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderConfigurationError(
            f"{provider_label} base URL must be an absolute HTTP(S) URL."
        )
    if parsed.username or parsed.password:
        raise ProviderConfigurationError(
            f"{provider_label} base URL must not contain credentials."
        )
    if parsed.query or parsed.fragment:
        raise ProviderConfigurationError(
            f"{provider_label} base URL must not contain a query or fragment."
        )
    return normalized


def http_status_error(provider_label: str, status: int) -> ProviderRequestError:
    stage = _stage_for_status(status)
    return ProviderRequestError(
        f"{provider_label} request failed during {stage} (HTTP {status}).",
        retryable=status in {408, 409, 425, 429} or status >= 500,
        stage=stage,
        status_code=status,
    )


def network_error(provider_label: str) -> ProviderRequestError:
    return ProviderRequestError(
        f"{provider_label} network request failed.",
        retryable=True,
        stage="network",
    )


def _stage_for_status(status: int) -> str:
    if status in {401, 403}:
        return "authentication"
    if status == 404:
        return "endpoint"
    if status == 429:
        return "rate_limit"
    return "request"


__all__ = ["http_status_error", "network_error", "validate_http_base_url"]
