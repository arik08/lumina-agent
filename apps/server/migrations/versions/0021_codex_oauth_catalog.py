"""Route Codex through ChatGPT OAuth and align its reviewed model catalog.

Revision ID: 0021
Revises: 0020
"""

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


provider_models = sa.table(
    "provider_models",
    sa.column("provider_id", sa.String()),
    sa.column("model_key", sa.String()),
    sa.column("enabled", sa.Boolean()),
    sa.column("is_default", sa.Boolean()),
    sa.column("sort_order", sa.Integer()),
    sa.column("capabilities_json", sa.JSON()),
    sa.column("catalog_revision", sa.String()),
    sa.column("verified_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        provider_models.update()
        .where(provider_models.c.provider_id == "codex")
        .values(
            catalog_revision="2026-07-12.2-codex-oauth",
            verified_at=datetime(2026, 7, 12, tzinfo=UTC),
        )
    )

    bind.execute(
        provider_models.update()
        .where(provider_models.c.provider_id == "codex")
        .values(is_default=False)
    )
    bind.execute(
        provider_models.update()
        .where(
            provider_models.c.provider_id == "codex",
            provider_models.c.model_key.in_(
                ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
            ),
        )
        .values(enabled=False)
    )
    bind.execute(
        provider_models.update()
        .where(
            provider_models.c.provider_id == "codex",
            provider_models.c.model_key == "gpt-5.5",
        )
        .values(enabled=True, is_default=True, sort_order=10)
    )
    bind.execute(
        provider_models.update()
        .where(
            provider_models.c.provider_id == "codex",
            provider_models.c.model_key == "gpt-5.4",
        )
        .values(enabled=True, is_default=False, sort_order=20)
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        provider_models.update()
        .where(provider_models.c.provider_id == "codex")
        .values(
            catalog_revision="2026-07-12.1",
            verified_at=datetime(2026, 7, 11, tzinfo=UTC),
        )
    )
    bind.execute(
        provider_models.update()
        .where(provider_models.c.provider_id == "codex")
        .values(is_default=False)
    )
    bind.execute(
        provider_models.update()
        .where(
            provider_models.c.provider_id == "codex",
            provider_models.c.model_key.in_(
                ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
            ),
        )
        .values(enabled=True)
    )
    bind.execute(
        provider_models.update()
        .where(
            provider_models.c.provider_id == "codex",
            provider_models.c.model_key == "gpt-5.6-sol",
        )
        .values(is_default=True, sort_order=10)
    )
    bind.execute(
        provider_models.update()
        .where(
            provider_models.c.provider_id == "codex",
            provider_models.c.model_key == "gpt-5.6-terra",
        )
        .values(sort_order=20)
    )
    bind.execute(
        provider_models.update()
        .where(
            provider_models.c.provider_id == "codex",
            provider_models.c.model_key == "gpt-5.6-luna",
        )
        .values(sort_order=30)
    )
    bind.execute(
        provider_models.update()
        .where(
            provider_models.c.provider_id == "codex",
            provider_models.c.model_key == "gpt-5.5",
        )
        .values(sort_order=40)
    )
    bind.execute(
        provider_models.update()
        .where(
            provider_models.c.provider_id == "codex",
            provider_models.c.model_key == "gpt-5.4",
        )
        .values(sort_order=50)
    )
