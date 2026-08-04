from pathlib import Path

import pytest
from pydantic import ValidationError

from lumina.config import (
    DEFAULT_DATA_DIR,
    DEFAULT_DATABASE_URL,
    Settings,
    get_settings,
)


def test_pytest_defaults_are_isolated_from_repository_runtime() -> None:
    settings = get_settings()

    assert settings.environment == "test"
    assert settings.data_dir != DEFAULT_DATA_DIR
    assert settings.database_url != DEFAULT_DATABASE_URL
    assert ".cache/pytest/runtime-" in settings.database_url.replace("\\", "/")


def test_explicit_database_url_is_not_replaced_by_process_environment(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///should-not-be-used.db")
    explicit = f"sqlite:///{(tmp_path / 'isolated.db').as_posix()}"

    settings = Settings(database_url=explicit, data_dir=tmp_path)

    assert settings.database_url == explicit


def test_dotenv_api_key_takes_priority_over_process_environment(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=dotenv-key\n", encoding="utf-8")

    settings = Settings(_env_file=env_file, data_dir=tmp_path)

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "dotenv-key"


def test_empty_dotenv_api_key_falls_back_to_process_environment(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")
    env_file = tmp_path / ".env"
    env_file.write_text('OPENAI_API_KEY=""\n', encoding="utf-8")

    settings = Settings(_env_file=env_file, data_dir=tmp_path)

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "process-key"


def test_launcher_storage_overrides_dotenv_without_changing_api_key_precedence(
    monkeypatch, tmp_path: Path
) -> None:
    dotenv_database = f"sqlite:///{(tmp_path / 'dotenv.db').as_posix()}"
    launcher_database = f"sqlite:///{(tmp_path / 'launcher.db').as_posix()}"
    launcher_files = tmp_path / "launcher-files"
    launcher_artifacts = tmp_path / "launcher-artifacts"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                f"DATABASE_URL={dotenv_database}",
                f"LUMINA_FILES_DIR={tmp_path / 'dotenv-files'}",
                f"LUMINA_ARTIFACTS_DIR={tmp_path / 'dotenv-artifacts'}",
                "OPENAI_API_KEY=dotenv-key",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LUMINA_LAUNCHER_DATABASE_URL", launcher_database)
    monkeypatch.setenv("LUMINA_LAUNCHER_FILES_DIR", str(launcher_files))
    monkeypatch.setenv("LUMINA_LAUNCHER_ARTIFACTS_DIR", str(launcher_artifacts))
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")

    settings = Settings(_env_file=env_file, data_dir=tmp_path)

    assert settings.database_url == launcher_database
    assert settings.files_dir == launcher_files.resolve()
    assert settings.artifacts_dir == launcher_artifacts.resolve()
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "dotenv-key"


def test_codex_cache_prewarm_is_opt_in(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LUMINA_CODEX_CACHE_PREWARM_ENABLED", raising=False)
    assert (
        Settings(_env_file=None, data_dir=tmp_path).codex_cache_prewarm_enabled is False
    )

    monkeypatch.setenv("LUMINA_CODEX_CACHE_PREWARM_ENABLED", "true")
    assert (
        Settings(_env_file=None, data_dir=tmp_path).codex_cache_prewarm_enabled is True
    )


def test_same_session_concurrency_cannot_be_raised(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="less than or equal to 1"):
        Settings(_env_file=None, data_dir=tmp_path, session_concurrency_limit=2)


@pytest.mark.parametrize(
    ("setting_name", "value"),
    [
        ("run_timeout_seconds", 30.0),
        ("run_token_limit", 10_000),
        ("run_cost_limit_usd", 2.5),
    ],
)
def test_legacy_run_limit_settings_warn_and_are_ignored(
    tmp_path: Path, setting_name: str, value: float | int
) -> None:
    with pytest.warns(
        UserWarning,
        match="Configure organization Run safety settings instead",
    ):
        settings = Settings(
            _env_file=None, data_dir=tmp_path, **{setting_name: value}
        )

    assert getattr(settings, setting_name) is None
