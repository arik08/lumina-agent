"""Remove retired GPT model generations from the provider catalog.

Revision ID: 0079
Revises: 0078
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.selectable import TableClause


revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None


_PROVIDERS = ("pgpt", "codex", "openai")
_DEFAULT_MODEL = "gpt-5.6-luna"


def _retired_model_filter(provider_models: TableClause) -> sa.ColumnElement[bool]:
    generation = sa.func.substr(provider_models.c.model_key, 7, 1)
    return sa.and_(
        provider_models.c.provider_id.in_(_PROVIDERS),
        provider_models.c.model_key.like("gpt-5.%"),
        generation.in_(("4", "5")),
    )


def upgrade() -> None:
    provider_models = sa.table(
        "provider_models",
        sa.column("provider_id", sa.String()),
        sa.column("model_key", sa.String()),
        sa.column("is_default", sa.Boolean()),
    )
    retired_filter = _retired_model_filter(provider_models)

    op.execute(
        provider_models.update()
        .where(provider_models.c.provider_id.in_(_PROVIDERS))
        .values(is_default=False)
    )
    op.execute(
        provider_models.update()
        .where(
            provider_models.c.provider_id.in_(_PROVIDERS),
            provider_models.c.model_key == _DEFAULT_MODEL,
        )
        .values(is_default=True)
    )
    op.execute(provider_models.delete().where(retired_filter))


def downgrade() -> None:
    # Retired models are intentionally not restored.
    pass
