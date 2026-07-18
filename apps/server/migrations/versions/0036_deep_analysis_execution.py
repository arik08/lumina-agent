"""Connect deep-analysis workflow nodes to durable Lumina Runs.

Revision ID: 0036
Revises: 0035
"""

from alembic import op
import sqlalchemy as sa


revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "surface", sa.String(length=32), nullable=False, server_default="chat"
            )
        )
        batch_op.create_index("ix_conversations_surface", ["surface"])

    with op.batch_alter_table("deep_analysis_missions") as batch_op:
        batch_op.add_column(
            sa.Column("conversation_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_deep_analysis_missions_conversation_id_conversations",
            "conversations",
            ["conversation_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_deep_analysis_missions_conversation_id", ["conversation_id"]
        )
        batch_op.add_column(
            sa.Column(
                "source_manifest_json", sa.JSON(), nullable=False, server_default="[]"
            )
        )

    with op.batch_alter_table("deep_analysis_workflow_nodes") as batch_op:
        batch_op.add_column(sa.Column("run_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column("output_project_file_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("output_logical_path", sa.String(length=1000), nullable=True)
        )
        batch_op.add_column(
            sa.Column("output_markdown", sa.Text(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column(
                "generated_files_json", sa.JSON(), nullable=False, server_default="[]"
            )
        )
        batch_op.add_column(
            sa.Column(
                "run_history_json", sa.JSON(), nullable=False, server_default="[]"
            )
        )
        batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_deep_analysis_workflow_nodes_run_id_runs",
            "runs",
            ["run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_da_nodes_output_file",
            "project_files",
            ["output_project_file_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_deep_analysis_workflow_nodes_run_id", ["run_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("deep_analysis_workflow_nodes") as batch_op:
        batch_op.drop_constraint(
            "uq_deep_analysis_workflow_nodes_run_id", type_="unique"
        )
        batch_op.drop_constraint(
            "fk_da_nodes_output_file",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_deep_analysis_workflow_nodes_run_id_runs", type_="foreignkey"
        )
        batch_op.drop_column("finished_at")
        batch_op.drop_column("started_at")
        batch_op.drop_column("error_message")
        batch_op.drop_column("run_history_json")
        batch_op.drop_column("generated_files_json")
        batch_op.drop_column("output_markdown")
        batch_op.drop_column("output_logical_path")
        batch_op.drop_column("output_project_file_id")
        batch_op.drop_column("run_id")

    with op.batch_alter_table("deep_analysis_missions") as batch_op:
        batch_op.drop_constraint(
            "uq_deep_analysis_missions_conversation_id", type_="unique"
        )
        batch_op.drop_constraint(
            "fk_deep_analysis_missions_conversation_id_conversations",
            type_="foreignkey",
        )
        batch_op.drop_column("source_manifest_json")
        batch_op.drop_column("conversation_id")

    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_index("ix_conversations_surface")
        batch_op.drop_column("surface")
