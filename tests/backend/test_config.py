from pathlib import Path

from lumina.config import Settings


def test_explicit_database_url_is_not_replaced_by_process_environment(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///should-not-be-used.db")
    explicit = f"sqlite:///{(tmp_path / 'isolated.db').as_posix()}"

    settings = Settings(database_url=explicit, data_dir=tmp_path)

    assert settings.database_url == explicit
