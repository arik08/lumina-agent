"""add durable prompt cache seeds

Revision ID: 0066
Revises: 0065
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from lumina.models import UTCDateTime


revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_cache_seeds",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=240), nullable=False),
        sa.Column("prompt_cache_key", sa.String(length=128), nullable=False),
        sa.Column("static_digest", sa.String(length=64), nullable=False),
        sa.Column("system_content", sa.Text(), nullable=False),
        sa.Column("tools_json", sa.JSON(), nullable=False),
        sa.Column("effort", sa.String(length=32), nullable=True),
        sa.Column("last_used_at", UTCDateTime(), nullable=False),
        sa.Column("last_warmed_at", UTCDateTime(), nullable=True),
        sa.Column("last_warm_input_tokens", sa.Integer(), nullable=True),
        sa.Column("last_warm_cached_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "prompt_cache_key",
            name="uq_prompt_cache_seeds_prompt_cache_key",
        ),
    )
    op.create_index(
        "ix_prompt_cache_seeds_user_id",
        "prompt_cache_seeds",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_prompt_cache_seeds_recent",
        "prompt_cache_seeds",
        ["last_used_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prompt_cache_seeds_recent",
        table_name="prompt_cache_seeds",
    )
    op.drop_index(
        "ix_prompt_cache_seeds_user_id",
        table_name="prompt_cache_seeds",
    )
    op.drop_table("prompt_cache_seeds")
