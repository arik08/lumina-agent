"""Make GPT-5.6-Luna the default GPT model.

Revision ID: 0080
Revises: 0079
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None


_PROVIDERS = ("pgpt", "codex", "openai")
_LUNA_MODEL = "gpt-5.6-luna"
_PREVIOUS_DEFAULT_MODEL = "gpt-5.6-sol"


def _set_default(model_key: str) -> None:
    provider_models = sa.table(
        "provider_models",
        sa.column("provider_id", sa.String()),
        sa.column("model_key", sa.String()),
        sa.column("is_default", sa.Boolean()),
    )
    bind = op.get_bind()

    for provider_id in _PROVIDERS:
        target_exists = bind.scalar(
            sa.select(sa.func.count())
            .select_from(provider_models)
            .where(
                provider_models.c.provider_id == provider_id,
                provider_models.c.model_key == model_key,
            )
        )
        if not target_exists:
            continue
        op.execute(
            provider_models.update()
            .where(provider_models.c.provider_id == provider_id)
            .values(is_default=False)
        )
        op.execute(
            provider_models.update()
            .where(
                provider_models.c.provider_id == provider_id,
                provider_models.c.model_key == model_key,
            )
            .values(is_default=True)
        )


def upgrade() -> None:
    _set_default(_LUNA_MODEL)


def downgrade() -> None:
    _set_default(_PREVIOUS_DEFAULT_MODEL)
