from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..config import DEFAULT_DATABASE_URL


class DiagnosticEnvironment(BaseSettings):
    """Secret-aware environment view used only by the diagnostic boundary."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr = SecretStr(DEFAULT_DATABASE_URL)
    pgpt_api_key: SecretStr | None = None
    pgpt_employee_no: SecretStr | None = None
    pgpt_company_code: SecretStr | None = None
    pgpt_base_url: str = ""
    pgpt_diagnostic_model: str = "gpt-5.4"
    lumina_ca_cert: str = ""
    lumina_ca_bundle: str = ""
    lumina_tls_compat_mode: bool = False

    @classmethod
    def load(cls, env_file: Path | None) -> "DiagnosticEnvironment":
        return cls(  # type: ignore[call-arg]
            _env_file=env_file if env_file and env_file.is_file() else None
        )

    def pgpt_environment(self) -> dict[str, str]:
        return {
            "PGPT_API_KEY": _secret_value(self.pgpt_api_key),
            "PGPT_EMPLOYEE_NO": _secret_value(self.pgpt_employee_no),
            "PGPT_COMPANY_CODE": _secret_value(self.pgpt_company_code),
            "PGPT_BASE_URL": self.pgpt_base_url.strip(),
        }

    def credential_values(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (
                _secret_value(self.pgpt_api_key),
                _secret_value(self.pgpt_employee_no),
                _secret_value(self.pgpt_company_code),
            )
            if value
        )


def _secret_value(value: SecretStr | None) -> str:
    return value.get_secret_value() if value is not None else ""


__all__ = ["DiagnosticEnvironment"]
