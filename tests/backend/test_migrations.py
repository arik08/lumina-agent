from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from lumina.db import Base
from lumina.migrations import SERVER_ROOT, upgrade_database
from lumina.models import (
    CompactedContextEntry,  # noqa: F401
    HelpItem,
    ProjectFolder,
    RuntimePromptOverride,
)


def test_alembic_upgrades_the_injected_database_url(tmp_path: Path) -> None:
    database = tmp_path / "migrated.db"
    database_url = f"sqlite:///{database.as_posix()}"

    upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        project_columns = {
            column["name"] for column in inspector.get_columns("projects")
        }
        organization_columns = {
            column["name"] for column in inspector.get_columns("organizations")
        }
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        extension_columns = {
            column["name"] for column in inspector.get_columns("extensions")
        }
        conversation_columns = {
            column["name"] for column in inspector.get_columns("conversations")
        }
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()

    assert revision is not None
    assert {
        "organizations",
        "users",
        "projects",
        "conversations",
        "runs",
        "run_events",
        "artifacts",
        "artifact_versions",
        "plans",
        "plan_steps",
        "plan_subtasks",
        "tool_approvals",
        "compacted_context_entries",
        "mcp_definitions",
        "mcp_configuration_revisions",
        "project_files",
        "project_file_versions",
        "project_folders",
        "help_items",
        "project_memories",
        "project_learning_proposals",
        "notifications",
        "announcements",
        "skill_ownerships",
        "runtime_prompt_overrides",
    } <= tables
    assert {"concept_revision", "concept_hash"} <= project_columns
    assert {
        "instructions",
        "instruction_revision",
        "instruction_digest",
    } <= project_columns
    assert {
        "policy_instructions",
        "policy_revision",
        "policy_digest",
        "policy_revision_labels",
        "policy_revision_contents",
        "run_safety_settings_json",
        "initial_execution_settings_json",
    } <= organization_columns
    assert {
        "personal_instructions",
        "personal_instruction_revision",
        "personal_instruction_digest",
        "affiliation",
    } <= user_columns
    assert "creator_user_id" in extension_columns
    assert "is_liked" in conversation_columns
    assert revision == "0030"


def test_structured_plan_migration_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "round-trip.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url)

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.downgrade(config, "0003")

    engine = create_engine(database_url)
    try:
        assert {"plans", "plan_steps"}.isdisjoint(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0003"
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        assert {"plans", "plan_steps"} <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0030"
            )
    finally:
        engine.dispose()


def test_context_compaction_memory_learning_migration_round_trip(
    tmp_path: Path,
) -> None:
    database = tmp_path / "context-memory-round-trip.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "compacted_context_entries" in inspector.get_table_names()
        assert "conflict_key" in {
            column["name"] for column in inspector.get_columns("user_memories")
        }
    finally:
        engine.dispose()

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.downgrade(config, "0004")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "compacted_context_entries" not in inspector.get_table_names()
        assert "conflict_key" not in {
            column["name"] for column in inspector.get_columns("user_memories")
        }
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0004"
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "compacted_context_entries" in inspector.get_table_names()
        assert "conflict_key" in {
            column["name"] for column in inspector.get_columns("user_memories")
        }
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0030"
            )
    finally:
        engine.dispose()


def test_context_migration_adopts_legacy_create_all_table(tmp_path: Path) -> None:
    database = tmp_path / "legacy-context-table.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url, "0004")

    engine = create_engine(database_url)
    try:
        Base.metadata.tables["compacted_context_entries"].create(engine)
        inspector = inspect(engine)
        assert "conflict_key" not in {
            column["name"] for column in inspector.get_columns("user_memories")
        }
        assert "compacted_context_entries" in inspector.get_table_names()
    finally:
        engine.dispose()

    upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "conflict_key" in {
            column["name"] for column in inspector.get_columns("user_memories")
        }
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0030"
            )
    finally:
        engine.dispose()


def test_recent_migrations_adopt_tables_precreated_by_runtime_schema(
    tmp_path: Path,
) -> None:
    database = tmp_path / "precreated-runtime-tables.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url, "0022")

    engine = create_engine(database_url)
    try:
        for table in (
            RuntimePromptOverride.__table__,
            ProjectFolder.__table__,
            HelpItem.__table__,
        ):
            table.create(engine)
    finally:
        engine.dispose()

    upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
        assert revision == "0030"
    finally:
        engine.dispose()


def test_notification_migration_0010_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "notification-round-trip.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url, "0010")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "notifications" in inspector.get_table_names()
        assert {
            "user_id",
            "kind",
            "idempotency_key",
            "deep_link_json",
            "read_at",
        } <= {column["name"] for column in inspector.get_columns("notifications")}
        assert {"ix_notifications_user_created", "ix_notifications_user_unread"} <= {
            index["name"] for index in inspector.get_indexes("notifications")
        }
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0010"
            )
    finally:
        engine.dispose()

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.downgrade(config, "0009")
    engine = create_engine(database_url)
    try:
        assert "notifications" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "0010")
    engine = create_engine(database_url)
    try:
        assert "notifications" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_plan_subtask_migration_0011_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "plan-subtask-round-trip.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url, "0011")

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    engine = create_engine(database_url)
    try:
        assert "plan_subtasks" in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.downgrade(config, "0010")
    engine = create_engine(database_url)
    try:
        assert "plan_subtasks" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0010"
            )
    finally:
        engine.dispose()

    command.upgrade(config, "0011")
    engine = create_engine(database_url)
    try:
        assert "plan_subtasks" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0011"
            )
    finally:
        engine.dispose()


def test_tool_approval_migration_0012_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "tool-approval-round-trip.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url, "0012")

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "tool_approvals" in inspector.get_table_names()
        assert {
            "run_id",
            "tool_call_id",
            "tool_name",
            "effect",
            "risk_level",
            "argument_digest",
            "summary_json",
            "status",
            "resolved_by_user_id",
        } <= {column["name"] for column in inspector.get_columns("tool_approvals")}
    finally:
        engine.dispose()

    command.downgrade(config, "0011")
    engine = create_engine(database_url)
    try:
        assert "tool_approvals" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "0012")
    engine = create_engine(database_url)
    try:
        assert "tool_approvals" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0012"
            )
    finally:
        engine.dispose()


def test_instruction_hierarchy_migration_0013_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "instruction-hierarchy-round-trip.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url, "0013")

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "policy_instructions" in {
            column["name"] for column in inspector.get_columns("organizations")
        }
        assert "personal_instructions" in {
            column["name"] for column in inspector.get_columns("users")
        }
        assert "instructions" in {
            column["name"] for column in inspector.get_columns("projects")
        }
    finally:
        engine.dispose()

    command.downgrade(config, "0012")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "policy_instructions" not in {
            column["name"] for column in inspector.get_columns("organizations")
        }
        assert "personal_instructions" not in {
            column["name"] for column in inspector.get_columns("users")
        }
        assert "instructions" not in {
            column["name"] for column in inspector.get_columns("projects")
        }
    finally:
        engine.dispose()

    command.upgrade(config, "0013")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0013"
            )
    finally:
        engine.dispose()
