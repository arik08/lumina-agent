"""persist organization, project, and personal instruction hierarchy

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-12 00:04:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "policy_instructions",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "policy_revision", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "policy_digest",
            sa.String(length=64),
            server_default=sa.text(f"'{_EMPTY_SHA256}'"),
            nullable=False,
        ),
    )

    op.add_column(
        "users",
        sa.Column(
            "personal_instructions",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "personal_instruction_revision",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "personal_instruction_digest",
            sa.String(length=64),
            server_default=sa.text(f"'{_EMPTY_SHA256}'"),
            nullable=False,
        ),
    )

    op.add_column(
        "projects",
        sa.Column(
            "instructions", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "instruction_revision",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "instruction_digest",
            sa.String(length=64),
            server_default=sa.text(f"'{_EMPTY_SHA256}'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "instruction_digest")
    op.drop_column("projects", "instruction_revision")
    op.drop_column("projects", "instructions")
    op.drop_column("users", "personal_instruction_digest")
    op.drop_column("users", "personal_instruction_revision")
    op.drop_column("users", "personal_instructions")
    op.drop_column("organizations", "policy_digest")
    op.drop_column("organizations", "policy_revision")
    op.drop_column("organizations", "policy_instructions")
