from __future__ import annotations

import os

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import JSON
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from lumina.diagnostics.postgres import (
    database_dialect,
    render_alembic_offline_sql,
    smoke_database,
)
from lumina.migrations import SERVER_ROOT, upgrade_database
from lumina.models import Base


POSTGRES_OFFLINE_URL = (
    "postgresql+psycopg://lumina:offline-placeholder@127.0.0.1/lumina"
)


def test_postgres_alembic_offline_head_contains_cross_dialect_contracts() -> None:
    sql = render_alembic_offline_sql(POSTGRES_OFFLINE_URL)
    normalized = " ".join(sql.split())
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    head = ScriptDirectory.from_config(config).get_current_head()

    assert head is not None and head in normalized
    assert "CREATE TABLE organizations" in normalized
    assert "CREATE TABLE mcp_definitions" in normalized
    assert "ADD COLUMN allowed_ip_ranges_json JSON" in normalized
    assert "ADD COLUMN header_templates_json JSON" in normalized
    assert "CREATE TABLE project_files" in normalized
    assert "CREATE TABLE project_memories" in normalized
    assert "CREATE TABLE knowledge_spaces" in normalized
    assert "CREATE TABLE knowledge_statements" in normalized
    assert " JSON " in normalized
    assert "uq_projects_default_owner" in normalized
    assert "WHERE is_default" in normalized
    assert "kind = 'rating' AND deleted_at IS NULL" in normalized
    assert "PRAGMA" not in normalized.upper()


def test_sqlalchemy_metadata_compiles_for_postgres_json_and_partial_indexes() -> None:
    dialect = postgresql.dialect()
    table_sql = "\n".join(
        str(CreateTable(table).compile(dialect=dialect))
        for table in Base.metadata.sorted_tables
    )
    index_sql = "\n".join(
        str(CreateIndex(index).compile(dialect=dialect))
        for table in Base.metadata.sorted_tables
        for index in table.indexes
    )

    json_columns = [
        column
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if isinstance(column.type, JSON)
    ]
    assert json_columns
    assert " JSON" in table_sql
    assert "CREATE UNIQUE INDEX uq_projects_default_owner" in index_sql
    assert "WHERE is_default" in index_sql
    assert "WHERE kind = 'rating' AND deleted_at IS NULL" in index_sql
    revision_table = Base.metadata.tables["mcp_configuration_revisions"]
    assert isinstance(revision_table.c.allowed_ip_ranges_json.type, JSON)
    assert isinstance(revision_table.c.header_templates_json.type, JSON)
    assert isinstance(
        Base.metadata.tables["knowledge_evidence_segments"].c.locator_json.type, JSON
    )
    assert isinstance(
        Base.metadata.tables["knowledge_statements"].c.object_value_json.type, JSON
    )


@pytest.mark.skipif(
    not os.getenv("LUMINA_TEST_POSTGRES_URL")
    or os.getenv("LUMINA_TEST_POSTGRES_ALLOW_MIGRATIONS") != "1",
    reason=(
        "A dedicated LUMINA_TEST_POSTGRES_URL and explicit "
        "LUMINA_TEST_POSTGRES_ALLOW_MIGRATIONS=1 are required"
    ),
)
def test_optional_live_postgres_upgrade_and_smoke() -> None:
    database_url = os.environ["LUMINA_TEST_POSTGRES_URL"]
    assert database_dialect(database_url) == "postgresql"
    upgrade_database(database_url)
    result = smoke_database(database_url)
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    assert result.current_revision == result.head_revision == expected_head
