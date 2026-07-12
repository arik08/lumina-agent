from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


SERVER_ROOT = Path(__file__).resolve().parents[2]


def upgrade_database(database_url: str, revision: str = "head") -> None:
    """Apply committed migrations using the application-selected database URL."""
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, revision)
