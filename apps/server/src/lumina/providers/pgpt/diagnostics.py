from __future__ import annotations

from dataclasses import dataclass

from lumina.http_client import redact_sensitive_text

from .auth import PgptCredentials, build_pgpt_auth_token


@dataclass(frozen=True, slots=True)
class PgptDiagnostic:
    stage: str
    ok: bool
    message: str
    status_code: int | None = None


def redact_pgpt_text(value: str, credentials: PgptCredentials | None = None) -> str:
    secrets: tuple[str, ...] = ()
    if credentials is not None:
        token = build_pgpt_auth_token(
            credentials.api_key,
            credentials.employee_no,
            credentials.company_code,
        )
        secrets = (
            credentials.api_key,
            credentials.employee_no,
            credentials.company_code,
            token,
        )
    return redact_sensitive_text(value, secrets=secrets)


def diagnostic_for_status(status_code: int) -> PgptDiagnostic:
    if status_code in {401, 403}:
        return PgptDiagnostic(
            "authentication", False, "P-GPT authentication failed.", status_code
        )
    if status_code == 404:
        return PgptDiagnostic(
            "endpoint", False, "P-GPT endpoint was not found.", status_code
        )
    if status_code == 429:
        return PgptDiagnostic(
            "rate_limit", False, "P-GPT rate limit was reached.", status_code
        )
    if status_code >= 500:
        return PgptDiagnostic(
            "provider", False, "P-GPT service is unavailable.", status_code
        )
    return PgptDiagnostic("request", False, "P-GPT request was rejected.", status_code)
