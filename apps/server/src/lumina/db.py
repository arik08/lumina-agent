from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def build_engine(database_url: str, **kwargs: Any) -> Engine:
    options: dict[str, Any] = {"pool_pre_ping": True, **kwargs}
    if database_url.startswith("sqlite"):
        options.setdefault("connect_args", {"check_same_thread": False})

    database_engine = create_engine(database_url, **options)
    if database_engine.dialect.name == "sqlite":

        @event.listens_for(database_engine, "connect")
        def configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()

        with database_engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql("PRAGMA synchronous=NORMAL")

    return database_engine


engine = build_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def configure_database(database_url: str) -> Engine:
    """Rebind the process database before application startup or isolated tests."""
    global engine
    engine.dispose()
    engine = build_engine(database_url)
    SessionLocal.configure(bind=engine)
    return engine


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_schema(bind: Engine | None = None) -> None:
    # Importing registers all mapped classes on Base.metadata.
    from . import models as _models  # noqa: F401
    from .deep_analysis import models as _deep_analysis_models  # noqa: F401

    Base.metadata.create_all(bind or engine)
