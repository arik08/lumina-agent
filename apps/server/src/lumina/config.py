from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast
from warnings import warn

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from .providers.constants import (
    DEFAULT_ANTHROPIC_BASE_URL,
    DEFAULT_GOOGLE_BASE_URL,
    DEFAULT_OPENAI_BASE_URL,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATA_DIR = REPOSITORY_ROOT / "data"
DEFAULT_DATABASE_URL = (
    f"sqlite:///{(DEFAULT_DATA_DIR / 'database' / 'lumina.db').as_posix()}"
)


@lru_cache(maxsize=None)
def _warn_legacy_run_limits(names: tuple[str, ...]) -> None:
    warn(
        f"Legacy Run limit settings are no longer supported: {', '.join(names)}. "
        "Configure organization Run safety settings instead; these values are "
        "ignored.",
        UserWarning,
        stacklevel=3,
    )


class DotenvFirstSettings(BaseSettings):
    """Prefer non-empty dotenv values while retaining environment fallback."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del cls, settings_cls

        def non_empty_dotenv_settings() -> dict[str, Any]:
            return {
                key: value
                for key, value in dotenv_settings().items()
                if not (isinstance(value, str) and not value.strip())
            }

        return (
            init_settings,
            cast(PydanticBaseSettingsSource, non_empty_dotenv_settings),
            env_settings,
            file_secret_settings,
        )


class Settings(DotenvFirstSettings):
    """Process configuration loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="LUMINA_",
        populate_by_name=True,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = Field(
        default=DEFAULT_DATABASE_URL,
        validation_alias=AliasChoices("DATABASE_URL", "LUMINA_DATABASE_URL"),
    )
    data_dir: Path = DEFAULT_DATA_DIR
    files_dir: Path | None = None
    artifacts_dir: Path | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "LUMINA_OPENAI_API_KEY"),
    )
    openai_base_url: str = Field(
        default=DEFAULT_OPENAI_BASE_URL,
        validation_alias=AliasChoices("OPENAI_BASE_URL", "LUMINA_OPENAI_BASE_URL"),
    )
    codex_image_model: str = Field(
        default="gpt-image-2",
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        validation_alias=AliasChoices("CODEX_IMAGE_MODEL", "LUMINA_CODEX_IMAGE_MODEL"),
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "LUMINA_ANTHROPIC_API_KEY"),
    )
    anthropic_base_url: str = Field(
        default=DEFAULT_ANTHROPIC_BASE_URL,
        validation_alias=AliasChoices(
            "ANTHROPIC_BASE_URL", "LUMINA_ANTHROPIC_BASE_URL"
        ),
    )
    google_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_API_KEY", "LUMINA_GOOGLE_API_KEY"),
    )
    google_base_url: str = Field(
        default=DEFAULT_GOOGLE_BASE_URL,
        validation_alias=AliasChoices("GOOGLE_BASE_URL", "LUMINA_GOOGLE_BASE_URL"),
    )
    # Generic compatible endpoints are operator-managed and deliberately use only
    # the Lumina-prefixed environment contract to avoid colliding with SDK globals.
    openai_compatible_api_key: SecretStr | None = None
    openai_compatible_base_url: str | None = None
    pgpt_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("PGPT_API_KEY", "LUMINA_PGPT_API_KEY"),
    )
    pgpt_employee_no: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("PGPT_EMPLOYEE_NO", "LUMINA_PGPT_EMPLOYEE_NO"),
    )
    pgpt_company_code: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("PGPT_COMPANY_CODE", "LUMINA_PGPT_COMPANY_CODE"),
    )
    pgpt_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("PGPT_BASE_URL", "LUMINA_PGPT_BASE_URL"),
    )

    auth_cookie_name: str = "lumina_session"
    csrf_cookie_name: str = "lumina_csrf"
    cookie_secure: bool = False

    session_concurrency_limit: int = Field(default=1, ge=1, le=1)
    user_concurrency_limit: int = Field(default=3, ge=1)
    server_concurrency_limit: int = Field(default=12, ge=1)
    tool_concurrency_limit: int = Field(default=4, ge=1, le=16)
    codex_cache_prewarm_enabled: bool = False
    run_timeout_seconds: float | None = Field(default=None, gt=0, le=86_400)
    run_token_limit: int | None = Field(default=None, ge=1)
    run_cost_limit_usd: float | None = Field(default=None, gt=0)
    login_max_failed_attempts: int = Field(default=5, ge=1)
    login_lock_seconds: int = Field(default=900, ge=1)
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    max_pasted_text_bytes: int = Field(default=2 * 1024 * 1024, ge=1024)
    python_execution_executable: Path | None = None
    python_heavy_execution_enabled: bool = False
    python_heavy_max_timeout_seconds: int = Field(
        default=24 * 60 * 60,
        ge=600,
        le=24 * 60 * 60,
    )

    @model_validator(mode="after")
    def resolve_storage_directories(self) -> "Settings":
        legacy_run_limits = {
            "run_timeout_seconds": self.run_timeout_seconds,
            "run_token_limit": self.run_token_limit,
            "run_cost_limit_usd": self.run_cost_limit_usd,
        }
        configured_legacy_limits = [
            name for name, value in legacy_run_limits.items() if value is not None
        ]
        if configured_legacy_limits:
            _warn_legacy_run_limits(tuple(configured_legacy_limits))
            for name in configured_legacy_limits:
                setattr(self, name, None)
        self.data_dir = self.data_dir.expanduser().resolve()
        self.files_dir = (
            (self.files_dir or self.data_dir / "files").expanduser().resolve()
        )
        self.artifacts_dir = (
            (self.artifacts_dir or self.data_dir / "artifacts").expanduser().resolve()
        )
        if self.python_execution_executable is not None:
            self.python_execution_executable = (
                self.python_execution_executable.expanduser().resolve()
            )
        if self.environment == "production":
            self.cookie_secure = True
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
