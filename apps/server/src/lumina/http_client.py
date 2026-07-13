from __future__ import annotations

import hashlib
import os
import re
import ssl
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import dotenv_values

try:
    import certifi
except ImportError:  # pragma: no cover - ssl defaults remain available
    certifi = None  # type: ignore[assignment]


class TrustConfigurationError(RuntimeError):
    """Raised when a configured trust source cannot be used safely."""


_PEM_CERTIFICATE = re.compile(
    rb"-----BEGIN CERTIFICATE-----\s+.*?-----END CERTIFICATE-----",
    re.DOTALL,
)
_TLS_COMPAT_CIPHER_LIST = "DEFAULT@SECLEVEL=1"
_AUTHORIZATION = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;]+)")
_NAMED_SECRET = re.compile(
    r'(?i)(["\']?(?:api[_-]?key|pgpt[_-]?api[_-]?key|token|'
    r'company[_-]?code|system[_-]?code|employee[_-]?no)["\']?\s*[:=]\s*["\'])'
    r'([^"\']+)(["\'])'
)


def redact_sensitive_text(value: str, *, secrets: tuple[str, ...] = ()) -> str:
    redacted = _AUTHORIZATION.sub(r"\1[REDACTED]", value)
    redacted = _NAMED_SECRET.sub(r"\1[REDACTED]\3", redacted)
    for secret in sorted(
        (secret for secret in secrets if secret), key=len, reverse=True
    ):
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


@dataclass(frozen=True, slots=True)
class TrustProfile:
    ssl_context: ssl.SSLContext
    bundle_path: Path | None
    company_ca_path: Path | None
    source: str
    tls_compat_mode: bool = False

    def subprocess_environment(
        self,
        base: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        result = dict(base or {})
        if self.bundle_path is None:
            return result
        bundle = str(self.bundle_path)
        node_ca = str(self.company_ca_path or self.bundle_path)
        result.update(
            {
                "SSL_CERT_FILE": bundle,
                "REQUESTS_CA_BUNDLE": bundle,
                "CURL_CA_BUNDLE": bundle,
                "PIP_CERT": bundle,
                "NODE_EXTRA_CA_CERTS": node_ca,
                "npm_config_cafile": bundle,
            }
        )
        if self.tls_compat_mode:
            option = f"--tls-cipher-list={_TLS_COMPAT_CIPHER_LIST}"
            existing = result.get("NODE_OPTIONS", "").strip()
            if option not in existing.split():
                result["NODE_OPTIONS"] = f"{existing} {option}".strip()
        return result


@dataclass(frozen=True, slots=True)
class HttpClientOptions:
    timeout_seconds: float = 30.0
    proxy: str | None = None
    trust_env: bool = False
    follow_redirects: bool = False


class TrustManager:
    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        ca_cert: Path | None = None,
        ca_bundle: Path | None = None,
        runtime_dir: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.repo_root = (repo_root or Path.cwd()).expanduser().resolve()
        if env is None:
            file_values = dotenv_values(self.repo_root / ".env")
            self._env = {
                key: value
                for key, value in file_values.items()
                if isinstance(value, str)
            }
            self._env.update(os.environ)
        else:
            self._env = dict(env)
        self._tls_compat_mode = self._env.get("LUMINA_TLS_COMPAT_MODE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._ca_cert = ca_cert
        self._ca_bundle = ca_bundle
        self.runtime_dir = (
            (runtime_dir or self.repo_root / "data" / "certs" / "runtime")
            .expanduser()
            .resolve()
        )

    def initialize(self, *, require_company_ca: bool = False) -> TrustProfile:
        configured_bundle = self._configured_path(
            self._ca_bundle,
            "LUMINA_CA_BUNDLE",
        )
        if configured_bundle is not None:
            self._require_file(configured_bundle, "combined CA bundle")
            company_ca = self._discover_optional_company_ca()
            return TrustProfile(
                ssl_context=self._context_from_bundle(
                    configured_bundle,
                    tls_compat_mode=self._tls_compat_mode,
                ),
                bundle_path=configured_bundle,
                company_ca_path=company_ca,
                source="configured_bundle",
                tls_compat_mode=self._tls_compat_mode,
            )

        company_ca = self._discover_company_ca()
        if company_ca is None:
            if require_company_ca:
                raise TrustConfigurationError(
                    "Company CA is required but LUMINA_CA_CERT and approved fallback files are unavailable."
                )
            return TrustProfile(
                ssl_context=ssl.create_default_context(),
                bundle_path=None,
                company_ca_path=None,
                source="public_ca_only",
                tls_compat_mode=False,
            )

        public_ca = self._public_ca_bundle()
        if public_ca is None:
            raise TrustConfigurationError(
                "A public CA bundle is required before the company CA can be combined."
            )
        combined = self._write_combined_bundle(public_ca, company_ca)
        return TrustProfile(
            ssl_context=self._context_from_bundle(
                combined,
                tls_compat_mode=self._tls_compat_mode,
            ),
            bundle_path=combined,
            company_ca_path=company_ca,
            source="public_and_company_ca",
            tls_compat_mode=self._tls_compat_mode,
        )

    def _configured_path(
        self,
        direct: Path | None,
        environment_name: str,
    ) -> Path | None:
        raw = (
            str(direct)
            if direct is not None
            else self._env.get(environment_name, "").strip()
        )
        if not raw:
            return None
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.repo_root / path
        return path.resolve()

    def _discover_company_ca(self) -> Path | None:
        explicitly_configured = self._configured_path(self._ca_cert, "LUMINA_CA_CERT")
        if explicitly_configured is not None:
            self._require_file(explicitly_configured, "company CA")
            return explicitly_configured

        candidates = (
            self.repo_root / "data" / "certs" / "company-ca.crt",
            Path("C:/POSCO_CA.crt"),
            Path("/run/secrets/lumina/company-ca.crt"),
        )
        return next(
            (candidate.resolve() for candidate in candidates if candidate.is_file()),
            None,
        )

    def _discover_optional_company_ca(self) -> Path | None:
        try:
            return self._discover_company_ca()
        except TrustConfigurationError:
            return None

    @staticmethod
    def _require_file(path: Path, label: str) -> None:
        if not path.is_file():
            raise TrustConfigurationError(f"Configured {label} does not exist: {path}")

    @staticmethod
    def _public_ca_bundle() -> Path | None:
        if certifi is not None:
            path = Path(certifi.where())
            if path.is_file():
                return path.resolve()
        default = ssl.get_default_verify_paths().cafile
        if default and Path(default).is_file():
            return Path(default).resolve()
        return None

    def _write_combined_bundle(self, public_ca: Path, company_ca: Path) -> Path:
        certificates: list[bytes] = []
        seen: set[str] = set()
        for source, label in ((public_ca, "public CA"), (company_ca, "company CA")):
            matches = _PEM_CERTIFICATE.findall(source.read_bytes())
            if not matches:
                raise TrustConfigurationError(
                    f"{label} file contains no PEM certificate: {source}"
                )
            for certificate in matches:
                normalized = certificate.strip() + b"\n"
                digest = hashlib.sha256(normalized).hexdigest()
                if digest not in seen:
                    seen.add(digest)
                    certificates.append(normalized)

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        destination = self.runtime_dir / "combined-ca.pem"
        fd, temporary_name = tempfile.mkstemp(
            prefix=".combined-ca-",
            suffix=".tmp",
            dir=self.runtime_dir,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(b"\n".join(certificates))
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
        finally:
            temporary.unlink(missing_ok=True)

        self._context_from_bundle(
            destination,
            tls_compat_mode=self._tls_compat_mode,
        )
        return destination

    @staticmethod
    def _context_from_bundle(
        path: Path,
        *,
        tls_compat_mode: bool = False,
    ) -> ssl.SSLContext:
        try:
            context = ssl.create_default_context()
            if tls_compat_mode:
                context.set_ciphers(_TLS_COMPAT_CIPHER_LIST)
                if hasattr(ssl, "VERIFY_X509_STRICT"):
                    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
            context.load_verify_locations(cafile=str(path))
            return context
        except (OSError, ssl.SSLError) as exc:
            raise TrustConfigurationError(
                f"CA bundle validation failed: {path}"
            ) from exc


def create_http_client(
    trust_profile: TrustProfile,
    *,
    options: HttpClientOptions | None = None,
    headers: Mapping[str, str] | None = None,
) -> httpx.AsyncClient:
    settings = options or HttpClientOptions()
    return httpx.AsyncClient(
        verify=trust_profile.ssl_context,
        timeout=httpx.Timeout(settings.timeout_seconds),
        proxy=settings.proxy,
        trust_env=settings.trust_env,
        follow_redirects=settings.follow_redirects,
        headers=dict(headers or {}),
    )


__all__ = [
    "HttpClientOptions",
    "TrustConfigurationError",
    "TrustManager",
    "TrustProfile",
    "create_http_client",
    "redact_sensitive_text",
]
