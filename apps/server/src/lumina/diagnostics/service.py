from __future__ import annotations

import socket
import ssl
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ..http_client import TrustConfigurationError, TrustManager, TrustProfile
from ..providers.errors import ProviderConfigurationError
from ..providers.pgpt.auth import (
    PgptCredentials,
    build_pgpt_authorization_header,
)
from ..providers.pgpt.profile import PgptProfile
from .environment import DiagnosticEnvironment
from .models import DiagnosticReport
from .postgres import database_dialect, render_alembic_offline_sql, smoke_database


def run_diagnostics(
    *,
    environment: DiagnosticEnvironment,
    repo_root: Path,
    network: bool = False,
    check_pgpt: bool = False,
    check_database: bool = False,
    require_company_ca: bool = False,
    require_postgres: bool = False,
    company_ca: Path | None = None,
    ca_bundle: Path | None = None,
    trust_runtime_dir: Path | None = None,
    timeout_seconds: float = 10.0,
) -> DiagnosticReport:
    report = DiagnosticReport()
    trust_profile = _check_trust(
        report,
        environment=environment,
        repo_root=repo_root,
        require_company_ca=require_company_ca,
        company_ca=company_ca,
        ca_bundle=ca_bundle,
        trust_runtime_dir=trust_runtime_dir,
    )
    if check_pgpt:
        _check_pgpt(
            report,
            environment=environment,
            trust_profile=trust_profile,
            network=network,
            timeout_seconds=timeout_seconds,
        )
    if check_database:
        _check_database(
            report,
            environment=environment,
            network=network,
            require_postgres=require_postgres,
        )
    return report


def _check_trust(
    report: DiagnosticReport,
    *,
    environment: DiagnosticEnvironment,
    repo_root: Path,
    require_company_ca: bool,
    company_ca: Path | None,
    ca_bundle: Path | None,
    trust_runtime_dir: Path | None,
) -> TrustProfile | None:
    try:
        ssl.create_default_context()
    except (OSError, ssl.SSLError):
        report.add("public_ca", "failed", "Public CA trust could not be initialized.")
        report.add("company_ca", "skipped", "Company CA validation was not attempted.")
        report.add("trust_bundle", "failed", "TLS trust initialization failed.")
        return None
    report.add("public_ca", "passed", "Public CA trust is available.")

    configured_ca = company_ca or _optional_path(environment.lumina_ca_cert)
    configured_bundle = ca_bundle or (
        None if company_ca is not None else _optional_path(environment.lumina_ca_bundle)
    )
    try:
        profile = TrustManager(
            repo_root=repo_root,
            ca_cert=configured_ca,
            ca_bundle=configured_bundle,
            runtime_dir=trust_runtime_dir,
            env={},
        ).initialize(require_company_ca=require_company_ca)
    except TrustConfigurationError:
        report.add(
            "company_ca",
            "failed",
            "Configured company CA or combined bundle is missing or invalid.",
        )
        report.add("trust_bundle", "failed", "TLS trust bundle validation failed.")
        return None

    if profile.company_ca_path is not None:
        report.add(
            "company_ca", "passed", "Company CA certificate chain was validated."
        )
    elif profile.source == "configured_bundle":
        report.add(
            "company_ca", "passed", "Configured combined CA bundle was validated."
        )
    else:
        report.add(
            "company_ca",
            "skipped",
            "No company CA was configured; public CA trust remains active.",
        )
    report.add("trust_bundle", "passed", "TLS verification remains enabled.")
    return profile


def _check_pgpt(
    report: DiagnosticReport,
    *,
    environment: DiagnosticEnvironment,
    trust_profile: TrustProfile | None,
    network: bool,
    timeout_seconds: float,
) -> None:
    pgpt_env = environment.pgpt_environment()
    try:
        profile = PgptProfile.from_env(pgpt_env)
    except ProviderConfigurationError:
        report.add(
            "endpoint_config", "failed", "P-GPT endpoint configuration is invalid."
        )
        profile = None
    else:
        report.add(
            "endpoint_config", "passed", "P-GPT endpoint configuration is valid."
        )

    try:
        credentials = PgptCredentials.from_env(pgpt_env)
    except ProviderConfigurationError:
        report.add("credentials", "failed", "P-GPT credentials are incomplete.")
        credentials = None
    else:
        report.add(
            "credentials", "passed", "P-GPT credentials are configured and redacted."
        )

    if not network:
        _skip_pgpt_network(report, "Network diagnostics were not requested.")
        return
    if profile is None or credentials is None or trust_profile is None:
        _skip_pgpt_network(
            report, "Static configuration must pass before network diagnostics."
        )
        return

    parsed = urlsplit(profile.base_url)
    assert parsed.hostname is not None
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        report.add("dns", "failed", "P-GPT DNS resolution failed.")
        _skip_after(report, "dns")
        return
    report.add(
        "dns", "passed", f"P-GPT DNS resolved {len(addresses)} address record(s)."
    )

    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            pass
    except OSError:
        report.add("connect", "failed", "P-GPT TCP connection failed.")
        _skip_after(report, "connect")
        return
    report.add("connect", "passed", "P-GPT TCP connection succeeded.")

    if parsed.scheme == "https":
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds) as raw:
                with trust_profile.ssl_context.wrap_socket(raw, server_hostname=host):
                    pass
        except (OSError, ssl.SSLError):
            report.add("tls", "failed", "P-GPT TLS verification failed.")
            _skip_after(report, "tls")
            return
        report.add("tls", "passed", "P-GPT TLS verification succeeded.")
    else:
        report.add("tls", "skipped", "The configured P-GPT endpoint does not use TLS.")

    try:
        response = _pgpt_probe(
            profile=profile,
            credentials=credentials,
            trust_profile=trust_profile,
            model=environment.pgpt_diagnostic_model,
            timeout_seconds=timeout_seconds,
        )
    except httpx.RequestError:
        report.add(
            "authentication", "skipped", "HTTP authentication could not be evaluated."
        )
        report.add("endpoint", "failed", "P-GPT HTTP request failed.")
        report.add("provider", "skipped", "Provider response was not available.")
        return

    status = response.status_code
    if status in {401, 403}:
        report.add("authentication", "failed", "P-GPT authentication was rejected.")
        report.add("endpoint", "skipped", "Endpoint mapping was not evaluated.")
        report.add("provider", "skipped", "Provider response was not evaluated.")
    elif status == 404:
        report.add(
            "authentication",
            "passed",
            "P-GPT authentication was accepted or not challenged.",
        )
        report.add("endpoint", "failed", "P-GPT API endpoint was not found.")
        report.add("provider", "skipped", "Provider response was not available.")
    elif 200 <= status < 300:
        report.add("authentication", "passed", "P-GPT authentication succeeded.")
        report.add("endpoint", "passed", "P-GPT API endpoint responded.")
        report.add(
            "provider", "passed", "P-GPT provider returned a successful response."
        )
    elif status == 429:
        report.add("authentication", "passed", "P-GPT authentication was accepted.")
        report.add("endpoint", "passed", "P-GPT API endpoint responded.")
        report.add("provider", "failed", "P-GPT rate limit was reached.")
    elif status >= 500:
        report.add(
            "authentication",
            "passed",
            "P-GPT authentication was accepted or not challenged.",
        )
        report.add("endpoint", "passed", "P-GPT API endpoint responded.")
        report.add("provider", "failed", "P-GPT provider is unavailable.")
    else:
        report.add(
            "authentication",
            "passed",
            "P-GPT authentication was accepted or not challenged.",
        )
        report.add("endpoint", "passed", "P-GPT API endpoint responded.")
        report.add("provider", "failed", "P-GPT rejected the diagnostic request.")


def _pgpt_probe(
    *,
    profile: PgptProfile,
    credentials: PgptCredentials,
    trust_profile: TrustProfile,
    model: str,
    timeout_seconds: float,
) -> httpx.Response:
    headers = {
        "Authorization": build_pgpt_authorization_header(credentials),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "model": profile.resolve_runtime_model(model),
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "stream": False,
        "max_tokens": 1,
    }
    with httpx.Client(
        verify=trust_profile.ssl_context,
        timeout=httpx.Timeout(timeout_seconds),
        trust_env=False,
        follow_redirects=False,
    ) as client:
        return client.post(profile.chat_completions_url, headers=headers, json=payload)


def _skip_pgpt_network(report: DiagnosticReport, message: str) -> None:
    for stage in ("dns", "connect", "tls", "authentication", "endpoint", "provider"):
        report.add(stage, "skipped", message)


def _skip_after(report: DiagnosticReport, failed_stage: str) -> None:
    stages = ("dns", "connect", "tls", "authentication", "endpoint", "provider")
    start = stages.index(failed_stage) + 1
    for stage in stages[start:]:
        report.add(stage, "skipped", f"Skipped after {failed_stage} failure.")


def _check_database(
    report: DiagnosticReport,
    *,
    environment: DiagnosticEnvironment,
    network: bool,
    require_postgres: bool,
) -> None:
    database_url = environment.database_url.get_secret_value()
    try:
        dialect = database_dialect(database_url)
    except (ValueError, TypeError):
        report.add("database_config", "failed", "DATABASE_URL is invalid.")
        report.add("alembic_offline", "skipped", "Database configuration is invalid.")
        if network:
            report.add(
                "database_connect", "skipped", "Database configuration is invalid."
            )
            report.add(
                "database_migration", "skipped", "Database configuration is invalid."
            )
        return
    if require_postgres and dialect != "postgresql":
        report.add(
            "database_config",
            "failed",
            "DATABASE_URL must use the PostgreSQL dialect for this check.",
        )
    else:
        report.add("database_config", "passed", f"Database dialect is {dialect}.")

    if dialect == "postgresql":
        try:
            offline_sql = render_alembic_offline_sql(database_url)
        except Exception:
            report.add(
                "alembic_offline",
                "failed",
                "PostgreSQL offline migration rendering failed.",
            )
        else:
            valid = "CREATE TABLE" in offline_sql and "alembic_version" in offline_sql
            report.add(
                "alembic_offline",
                "passed" if valid else "failed",
                (
                    "PostgreSQL offline migration SQL rendered successfully."
                    if valid
                    else "PostgreSQL offline migration SQL was incomplete."
                ),
            )
    else:
        report.add(
            "alembic_offline", "skipped", "PostgreSQL offline SQL was not requested."
        )

    if not network:
        return
    try:
        result = smoke_database(database_url)
    except Exception:
        report.add(
            "database_connect", "failed", "Database connection smoke test failed."
        )
        report.add(
            "database_migration", "skipped", "Migration head could not be checked."
        )
        return
    report.add("database_connect", "passed", "Database SELECT 1 smoke test succeeded.")
    if result.current_revision == result.head_revision:
        report.add(
            "database_migration", "passed", "Database is at the Alembic head revision."
        )
    else:
        report.add(
            "database_migration",
            "failed",
            "Database is not at the Alembic head revision.",
        )


def _optional_path(value: str) -> Path | None:
    clean = value.strip()
    return Path(clean) if clean else None


__all__ = ["run_diagnostics"]
