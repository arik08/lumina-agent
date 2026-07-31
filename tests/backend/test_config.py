from pathlib import Path

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


def test_codex_cache_prewarm_is_opt_in(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LUMINA_CODEX_CACHE_PREWARM_ENABLED", raising=False)
    assert (
        Settings(_env_file=None, data_dir=tmp_path).codex_cache_prewarm_enabled is False
    )

    monkeypatch.setenv("LUMINA_CODEX_CACHE_PREWARM_ENABLED", "true")
    assert (
        Settings(_env_file=None, data_dir=tmp_path).codex_cache_prewarm_enabled is True
    )
