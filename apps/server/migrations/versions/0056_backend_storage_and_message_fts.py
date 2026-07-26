"""compact legacy plan JSON and add SQLite message search FTS

Revision ID: 0056
Revises: 0055
"""

from __future__ import annotations

from alembic import context, op


revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if context.get_context().dialect.name != "sqlite":
        return
    op.execute(
        "UPDATE run_events SET payload_json = json_remove("
        "payload_json, '$.plan', '$.step.subtasks') "
        "WHERE event_type = 'plan_step_changed' "
        "AND json_valid(payload_json) "
        "AND (json_type(payload_json, '$.plan') IS NOT NULL "
        "OR json_type(payload_json, '$.step.subtasks') IS NOT NULL)"
    )
    op.execute(
        "UPDATE runs SET snapshot_json = json_remove(snapshot_json, '$.plan') "
        "WHERE json_valid(snapshot_json) "
        "AND json_type(snapshot_json, '$.plan') IS NOT NULL"
    )
    op.execute(
        "CREATE VIRTUAL TABLE message_search_fts USING fts5("
        "canonical_text, conversation_id UNINDEXED, "
        "content='messages', content_rowid='rowid', tokenize='trigram')"
    )
    op.execute("INSERT INTO message_search_fts(message_search_fts) VALUES ('rebuild')")
    op.execute(
        "CREATE TRIGGER trg_messages_search_fts_ai AFTER INSERT ON messages "
        "BEGIN INSERT INTO message_search_fts(rowid, canonical_text, conversation_id) "
        "VALUES (new.rowid, new.canonical_text, new.conversation_id); END"
    )
    op.execute(
        "CREATE TRIGGER trg_messages_search_fts_ad AFTER DELETE ON messages "
        "BEGIN INSERT INTO message_search_fts("
        "message_search_fts, rowid, canonical_text, conversation_id) "
        "VALUES ('delete', old.rowid, old.canonical_text, old.conversation_id); END"
    )
    op.execute(
        "CREATE TRIGGER trg_messages_search_fts_au AFTER UPDATE ON messages "
        "BEGIN INSERT INTO message_search_fts("
        "message_search_fts, rowid, canonical_text, conversation_id) "
        "VALUES ('delete', old.rowid, old.canonical_text, old.conversation_id); "
        "INSERT INTO message_search_fts(rowid, canonical_text, conversation_id) "
        "VALUES (new.rowid, new.canonical_text, new.conversation_id); END"
    )


def downgrade() -> None:
    if context.get_context().dialect.name != "sqlite":
        return
    for suffix in ("au", "ad", "ai"):
        op.execute(f"DROP TRIGGER trg_messages_search_fts_{suffix}")
    op.execute("DROP TABLE message_search_fts")
