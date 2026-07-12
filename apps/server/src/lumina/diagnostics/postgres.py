from __future__ import annotations

import io
from contextlib import redirect_stdout
from dataclasses import dataclass

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from ..migrations import SERVER_ROOT


@dataclass(frozen=True, slots=True)
class DatabaseSmokeResult:
    dialect: str
    current_revision: str | None
    head_revision: str


def database_dialect(database_url: str) -> str:
    return make_url(database_url).get_backend_name()


def render_alembic_offline_sql(database_url: str) -> str:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    output = io.StringIO()
    with redirect_stdout(output):
        command.upgrade(config, "head", sql=True)
    return output.getvalue()


def smoke_database(database_url: str) -> DatabaseSmokeResult:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("Alembic has no current head revision.")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            current = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
    return DatabaseSmokeResult(
        dialect=database_dialect(database_url),
        current_revision=current,
        head_revision=head,
    )


__all__ = [
    "DatabaseSmokeResult",
    "database_dialect",
    "render_alembic_offline_sql",
    "smoke_database",
]
