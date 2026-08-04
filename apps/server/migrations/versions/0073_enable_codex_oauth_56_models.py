"""Enable the live-verified GPT-5.6 family for Codex OAuth.

Revision ID: 0073
Revises: 0072
"""

from __future__ import annotations

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


_MODEL_ORDER = {
    "gpt-5.6-sol": 10,
    "gpt-5.6-terra": 20,
    "gpt-5.6-luna": 30,
}

provider_models = sa.table(
    "provider_models",
    sa.column("provider_id", sa.String()),
    sa.column("model_key", sa.String()),
    sa.column("enabled", sa.Boolean()),
    sa.column("sort_order", sa.Integer()),
    sa.column("source", sa.String()),
    sa.column("catalog_revision", sa.String()),
    sa.column("verified_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    bind = op.get_bind()
    for model_key, sort_order in _MODEL_ORDER.items():
        bind.execute(
            provider_models.update()
            .where(
                provider_models.c.provider_id == "codex",
                provider_models.c.model_key == model_key,
                provider_models.c.source != "admin_manual",
            )
            .values(
                enabled=True,
                sort_order=sort_order,
                catalog_revision="2026-08-05.1-codex-oauth-5.6",
                verified_at=datetime(2026, 8, 5, tzinfo=UTC),
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        provider_models.update()
        .where(
            provider_models.c.provider_id == "codex",
            provider_models.c.model_key.in_(tuple(_MODEL_ORDER)),
            provider_models.c.source != "admin_manual",
        )
        .values(
            enabled=False,
            catalog_revision="2026-07-12.2-codex-oauth",
            verified_at=datetime(2026, 7, 12, tzinfo=UTC),
        )
    )
