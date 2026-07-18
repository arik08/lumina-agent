"""add SQLite FTS5 indexes for Knowledge search

Revision ID: 0048
Revises: 0047
"""

from __future__ import annotations

from alembic import context, op


revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


FTS_INDEXES = (
    (
        "knowledge_entity_fts",
        "knowledge_entities",
        ("canonical_name", "entity_type", "description"),
    ),
    (
        "knowledge_statement_fts",
        "knowledge_statements",
        ("predicate_key", "object_value_json"),
    ),
    ("knowledge_source_fts", "knowledge_sources", ("title",)),
    ("knowledge_evidence_fts", "knowledge_evidence_segments", ("text",)),
)


def upgrade() -> None:
    if context.get_context().dialect.name != "sqlite":
        return
    for index_name, content_table, columns in FTS_INDEXES:
        _create_external_content_index(index_name, content_table, columns)


def downgrade() -> None:
    if context.get_context().dialect.name != "sqlite":
        return
    for index_name, content_table, _columns in reversed(FTS_INDEXES):
        for suffix in ("au", "ad", "ai"):
            op.execute(f"DROP TRIGGER trg_{content_table}_fts_{suffix}")
        op.execute(f"DROP TABLE {index_name}")


def _create_external_content_index(
    index_name: str, content_table: str, columns: tuple[str, ...]
) -> None:
    column_list = ", ".join(columns)
    new_values = ", ".join(f"new.{column}" for column in columns)
    old_values = ", ".join(f"old.{column}" for column in columns)
    op.execute(
        f"CREATE VIRTUAL TABLE {index_name} USING fts5("
        f"{column_list}, content='{content_table}', content_rowid='rowid', "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    op.execute(f"INSERT INTO {index_name}({index_name}) VALUES ('rebuild')")
    op.execute(
        f"CREATE TRIGGER trg_{content_table}_fts_ai AFTER INSERT ON {content_table} "
        f"BEGIN INSERT INTO {index_name}(rowid, {column_list}) "
        f"VALUES (new.rowid, {new_values}); END"
    )
    op.execute(
        f"CREATE TRIGGER trg_{content_table}_fts_ad AFTER DELETE ON {content_table} "
        f"BEGIN INSERT INTO {index_name}({index_name}, rowid, {column_list}) "
        f"VALUES ('delete', old.rowid, {old_values}); END"
    )
    op.execute(
        f"CREATE TRIGGER trg_{content_table}_fts_au AFTER UPDATE ON {content_table} "
        f"BEGIN INSERT INTO {index_name}({index_name}, rowid, {column_list}) "
        f"VALUES ('delete', old.rowid, {old_values}); "
        f"INSERT INTO {index_name}(rowid, {column_list}) "
        f"VALUES (new.rowid, {new_values}); END"
    )
