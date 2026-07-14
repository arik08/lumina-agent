"""Order Codex models by the reviewed 5.6 family before older models.

Revision ID: 0026
Revises: 0025
"""

from alembic import op
import sqlalchemy as sa


revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


provider_models = sa.table(
    "provider_models",
    sa.column("provider_id", sa.String()),
    sa.column("model_key", sa.String()),
    sa.column("sort_order", sa.Integer()),
)


def _set_codex_order(order: tuple[tuple[str, int], ...]) -> None:
    bind = op.get_bind()
    for model_key, sort_order in order:
        bind.execute(
            provider_models.update()
            .where(
                provider_models.c.provider_id == "codex",
                provider_models.c.model_key == model_key,
            )
            .values(sort_order=sort_order)
        )


def upgrade() -> None:
    _set_codex_order(
        (
            ("gpt-5.6-sol", 10),
            ("gpt-5.6-terra", 20),
            ("gpt-5.6-luna", 30),
            ("gpt-5.5", 40),
            ("gpt-5.4", 50),
        )
    )


def downgrade() -> None:
    _set_codex_order(
        (
            ("gpt-5.6-sol", 10),
            ("gpt-5.6-terra", 20),
            ("gpt-5.6-luna", 30),
            ("gpt-5.5", 10),
            ("gpt-5.4", 20),
        )
    )
