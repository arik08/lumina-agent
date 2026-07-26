import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


SERVER_ROOT = Path(__file__).resolve().parents[2] / "apps" / "server"


def _columns(database_path: Path, table: str) -> set[str]:
    with sqlite3.connect(database_path) as connection:
        return {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})")
        }


def test_settings_revision_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    database_path = tmp_path / "lumina.db"
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = f"sqlite:///{database_path.as_posix()}"

    command.upgrade(config, "head")

    assert "settings_revision" in _columns(database_path, "users")
    assert "settings_revision" in _columns(database_path, "projects")

    command.downgrade(config, "0028")

    assert "settings_revision" not in _columns(database_path, "users")
    assert "settings_revision" not in _columns(database_path, "projects")
