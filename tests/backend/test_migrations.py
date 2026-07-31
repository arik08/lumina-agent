from __future__ import annotations

import json
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

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
    executor_logger = logging.getLogger("lumina.agent.executor")
    executor_logger.disabled = False

    upgrade_database(database_url)

    assert executor_logger.disabled is False
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
        extension_version_columns = {
            column["name"] for column in inspector.get_columns("extension_versions")
        }
        conversation_columns = {
            column["name"] for column in inspector.get_columns("conversations")
        }
        run_columns = {column["name"] for column in inspector.get_columns("runs")}
        run_indexes = {index["name"] for index in inspector.get_indexes("runs")}
        run_event_indexes = {
            index["name"] for index in inspector.get_indexes("run_events")
        }
        deep_analysis_event_indexes = {
            index["name"] for index in inspector.get_indexes("deep_analysis_events")
        }
        all_index_names = {
            index["name"]
            for table_name in (
                "plan_steps",
                "plan_subtasks",
                "messages",
                "tool_executions",
            )
            for index in inspector.get_indexes(table_name)
        } | run_indexes
        run_unique_constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("runs")
        }
        workflow_node_columns = {
            column["name"]
            for column in inspector.get_columns("deep_analysis_workflow_nodes")
        }
        knowledge_tag_columns = {
            column["name"] for column in inspector.get_columns("knowledge_tags")
        }
        knowledge_document_columns = {
            column["name"] for column in inspector.get_columns("knowledge_documents")
        }
        knowledge_document_indexes = {
            index["name"] for index in inspector.get_indexes("knowledge_documents")
        }
        knowledge_space_columns = {
            column["name"] for column in inspector.get_columns("knowledge_spaces")
        }
        prompt_cache_seed_columns = {
            column["name"] for column in inspector.get_columns("prompt_cache_seeds")
        }
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
            knowledge_fts_trigger_count = connection.scalar(
                text(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' "
                    "AND name LIKE 'trg_knowledge_%_fts_%'"
                )
            )
            message_fts_trigger_count = connection.scalar(
                text(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' "
                    "AND name LIKE 'trg_messages_search_fts_%'"
                )
            )
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
        "announcement_receipts",
        "skill_ownerships",
        "runtime_prompt_overrides",
        "deep_analysis_missions",
        "deep_analysis_workflow_revisions",
        "deep_analysis_workflow_nodes",
        "deep_analysis_workflow_edges",
        "deep_analysis_decisions",
        "deep_analysis_decision_responses",
        "deep_analysis_quality_gate_results",
        "deep_analysis_claims",
        "deep_analysis_evidence_references",
        "deep_analysis_claim_evidence_links",
        "deep_analysis_open_issues",
        "deep_analysis_mission_exports",
        "deep_analysis_workflow_patterns",
        "deep_analysis_workflow_pattern_versions",
        "deep_analysis_events",
        "deep_analysis_commands",
        "deep_analysis_context_manifests",
        "deep_analysis_mission_file_links",
        "knowledge_spaces",
        "knowledge_documents",
        "knowledge_tags",
        "knowledge_tag_aliases",
        "knowledge_document_tags",
        "knowledge_tag_proposals",
        "prompt_cache_seeds",
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
    assert {
        "change_summary",
        "change_type",
        "restored_from_version_id",
    } <= extension_version_columns
    assert "is_liked" in conversation_columns
    assert "surface" in conversation_columns
    assert "next_turn_index" in conversation_columns
    assert "actual_cost_microusd" in workflow_node_columns
    assert "estimated_cost_microusd" not in workflow_node_columns
    assert knowledge_fts_trigger_count == 0
    assert "message_search_fts" in tables
    assert message_fts_trigger_count == 3
    assert {"is_favorite", "is_liked", "last_export_requested_at"} <= {
        column["name"] for column in inspector.get_columns("deep_analysis_missions")
    }
    assert {"project_ids_json", "use_mode"} <= knowledge_space_columns
    assert "conversation_id" in workflow_node_columns
    assert {"definition", "parent_tag_id", "revision"} <= knowledge_tag_columns
    assert {
        "source_artifact_id",
        "source_artifact_version_id",
    } <= knowledge_document_columns
    assert {
        "ix_knowledge_documents_source_artifact_id",
        "ix_knowledge_documents_source_artifact_version_id",
    } <= knowledge_document_indexes
    assert {
        "user_id",
        "provider_id",
        "model",
        "prompt_cache_key",
        "static_digest",
        "system_content",
        "tools_json",
        "last_used_at",
        "last_warmed_at",
        "last_warm_input_tokens",
        "last_warm_cached_tokens",
    } <= prompt_cache_seed_columns
    assert revision == "0072"
    assert "ix_run_events_run_type" in run_event_indexes
    assert "ix_run_events_replay" not in run_event_indexes
    assert "ix_deep_analysis_events_replay" not in deep_analysis_event_indexes
    assert (
        not {
            "ix_runs_conversation_id",
            "ix_runs_user_id",
            "ix_runs_status",
            "ix_plan_steps_timeline",
            "ix_plan_steps_plan_id",
            "ix_plan_subtasks_timeline",
            "ix_plan_subtasks_plan_step_id",
            "ix_messages_conversation_id",
            "ix_tool_executions_run_id",
        }
        & all_index_names
    )
    assert "ix_runs_queue_claim" in run_indexes
    assert "ix_runs_queue_order" in run_indexes
    assert "ix_runs_worker_lease" in run_indexes
    assert "uq_runs_conversation_user_idempotency" in run_unique_constraints
    assert {"worker_id", "heartbeat_at", "lease_expires_at"}.issubset(run_columns)


def test_migration_0072_cleans_legacy_mission_orphans(tmp_path: Path) -> None:
    database = tmp_path / "legacy-deep-analysis-orphans.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url, "0071")

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO deep_analysis_events "
                    "(mission_id, sequence, event_type, payload_json, id, created_at) "
                    "VALUES ('missing-mission', 1, 'legacy', '{}', "
                    "'orphan-event', '2026-08-01T00:00:00+00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO deep_analysis_workflow_pattern_versions "
                    "(pattern_id, version_number, status, definition_json, "
                    "definition_digest, change_summary, source_mission_id, id, "
                    "created_at, updated_at) VALUES "
                    "('missing-pattern', 1, 'draft', '{}', 'digest', 'legacy', "
                    "'missing-mission', 'orphan-pattern-version', "
                    "'2026-08-01T00:00:00+00:00', "
                    "'2026-08-01T00:00:00+00:00')"
                )
            )
            for statement in (
                "INSERT INTO deep_analysis_claim_evidence_links "
                "(id, claim_id, evidence_id, stance, rationale, created_at, "
                "updated_at) VALUES ('orphan-link', 'missing-claim', "
                "'missing-evidence', 'supports', 'legacy', "
                "'2026-08-01T00:00:00+00:00', "
                "'2026-08-01T00:00:00+00:00')",
                "INSERT INTO deep_analysis_decision_responses "
                "(id, decision_id, selected_option_id, answer_text, "
                "decided_by_user_id, created_at, updated_at) VALUES "
                "('orphan-response', 'missing-decision', 'option', 'legacy', "
                "'missing-user', '2026-08-01T00:00:00+00:00', "
                "'2026-08-01T00:00:00+00:00')",
                "INSERT INTO deep_analysis_workflow_edges "
                "(workflow_revision_id, source_node_key, target_node_key, "
                "edge_type, id, created_at, updated_at) VALUES "
                "('missing-revision', 'source', 'target', 'depends_on', "
                "'orphan-edge', '2026-08-01T00:00:00+00:00', "
                "'2026-08-01T00:00:00+00:00')",
                "INSERT INTO deep_analysis_workflow_nodes "
                "(workflow_revision_id, node_key, node_type, title, purpose, "
                "status, sequence, position_x, position_y, config_json, "
                "output_summary, actual_cost_microusd, id, created_at, "
                "updated_at) VALUES ('missing-revision', 'node', 'research', "
                "'Legacy', 'legacy', 'pending', 1, 0, 0, '{}', '', 0, "
                "'orphan-node', '2026-08-01T00:00:00+00:00', "
                "'2026-08-01T00:00:00+00:00')",
            ):
                connection.execute(text(statement))
    finally:
        engine.dispose()

    upgrade_database(database_url, "0072")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            event_count = connection.scalar(
                text(
                    "SELECT COUNT(*) FROM deep_analysis_events "
                    "WHERE id = 'orphan-event'"
                )
            )
            source_mission_id = connection.scalar(
                text(
                    "SELECT source_mission_id "
                    "FROM deep_analysis_workflow_pattern_versions "
                    "WHERE id = 'orphan-pattern-version'"
                )
            )
            revision = MigrationContext.configure(connection).get_current_revision()
            descendant_count = sum(
                int(
                    connection.scalar(
                        text(f"SELECT COUNT(*) FROM {table_name} WHERE id = :id"),
                        {"id": row_id},
                    )
                    or 0
                )
                for table_name, row_id in (
                    ("deep_analysis_claim_evidence_links", "orphan-link"),
                    ("deep_analysis_decision_responses", "orphan-response"),
                    ("deep_analysis_workflow_edges", "orphan-edge"),
                    ("deep_analysis_workflow_nodes", "orphan-node"),
                )
            )
    finally:
        engine.dispose()

    assert event_count == 0
    assert source_mission_id is None
    assert descendant_count == 0
    assert revision == "0072"


def test_message_search_fts_migration_0056_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "message-fts-round-trip.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url, "0055")

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO run_events "
                    "(id, run_id, conversation_id, sequence, event_type, "
                    "payload_json, created_at) VALUES "
                    "(:id, :run_id, :conversation_id, 1, "
                    "'plan_step_changed', :payload, :created_at)"
                ),
                {
                    "id": "event-legacy-plan",
                    "run_id": "run-legacy-plan",
                    "conversation_id": "conversation-legacy-plan",
                    "payload": json.dumps(
                        {
                            "plan": {"steps": [{"large": "duplicate"}]},
                            "step": {
                                "stepKey": "tools",
                                "subtasks": [{"id": "duplicate-subtask"}],
                            },
                            "reason": "preserved",
                        }
                    ),
                    "created_at": "2026-07-19T00:00:00+00:00",
                },
            )
    finally:
        engine.dispose()

    upgrade_database(database_url, "0056")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            cleaned_payload = json.loads(
                connection.scalar(
                    text(
                        "SELECT payload_json FROM run_events "
                        "WHERE id = 'event-legacy-plan'"
                    )
                )
            )
    finally:
        engine.dispose()
    assert "plan" not in cleaned_payload
    assert "subtasks" not in cleaned_payload["step"]
    assert cleaned_payload["reason"] == "preserved"

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.downgrade(config, "0055")

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
            trigger_count = connection.scalar(
                text(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' "
                    "AND name LIKE 'trg_messages_search_fts_%'"
                )
            )
    finally:
        engine.dispose()

    assert "message_search_fts" not in tables
    assert trigger_count == 0
    assert revision == "0055"


def test_knowledge_fts_migration_0048_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "knowledge-fts-round-trip.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url, "0048")

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.downgrade(config, "0047")

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
            trigger_count = connection.scalar(
                text(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' "
                    "AND name LIKE 'trg_knowledge_%_fts_%'"
                )
            )
    finally:
        engine.dispose()

    assert (
        not {
            "knowledge_entity_fts",
            "knowledge_statement_fts",
            "knowledge_source_fts",
            "knowledge_evidence_fts",
        }
        & tables
    )
    assert trigger_count == 0
    assert revision == "0047"


def test_deep_analysis_node_estimated_cost_migration_0049_round_trip(
    tmp_path: Path,
) -> None:
    database = tmp_path / "deep-analysis-node-cost-round-trip.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url, "0049")

    engine = create_engine(database_url)
    try:
        columns = {
            column["name"]
            for column in inspect(engine).get_columns("deep_analysis_workflow_nodes")
        }
    finally:
        engine.dispose()
    assert "estimated_cost_microusd" not in columns

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.downgrade(config, "0048")

    engine = create_engine(database_url)
    try:
        columns = {
            column["name"]
            for column in inspect(engine).get_columns("deep_analysis_workflow_nodes")
        }
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
    assert "estimated_cost_microusd" in columns
    assert revision == "0048"


def test_structured_plan_migration_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "round-trip.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url, "0051")

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

    command.upgrade(config, "0051")
    engine = create_engine(database_url)
    try:
        assert {"plans", "plan_steps"} <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0051"
            )
    finally:
        engine.dispose()


def test_context_compaction_memory_learning_migration_round_trip(
    tmp_path: Path,
) -> None:
    database = tmp_path / "context-memory-round-trip.db"
    database_url = f"sqlite:///{database.as_posix()}"
    upgrade_database(database_url, "0051")

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

    command.upgrade(config, "0051")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "compacted_context_entries" in inspector.get_table_names()
        assert "conflict_key" in {
            column["name"] for column in inspector.get_columns("user_memories")
        }
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision() == "0051"
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
                MigrationContext.configure(connection).get_current_revision() == "0072"
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
        assert revision == "0072"
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
