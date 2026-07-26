from pathlib import Path

from sqlalchemy import JSON, Column, MetaData, Table, insert

from lumina.db import build_engine


def test_sqlite_engine_uses_compact_utf8_json_without_pre_ping(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{(tmp_path / 'json.db').as_posix()}")
    metadata = MetaData()
    probe = Table("json_probe", metadata, Column("payload", JSON, nullable=False))
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(probe).values(payload={"label": "한글", "items": [1, 2]})
        )
        stored = connection.exec_driver_sql("SELECT payload FROM json_probe").scalar_one()

    assert engine.pool._pre_ping is False  # type: ignore[attr-defined]
    assert stored == '{"label":"한글","items":[1,2]}'
    engine.dispose()
