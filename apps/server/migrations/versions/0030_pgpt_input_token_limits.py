"""Record measured P-GPT input token limits.

Revision ID: 0030
Revises: 0029
"""

from alembic import op


revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


_INPUT_LIMITS = {
    "gpt-5.4": 911_900,
    "gpt-5.4-mini": 270_000,
    "gpt-5.5": 911_900,
}


def upgrade() -> None:
    bind = op.get_bind()
    for model_key, max_input_tokens in _INPUT_LIMITS.items():
        if bind.dialect.name == "postgresql":
            capabilities_update = (
                "CAST(CAST(capabilities_json AS JSONB) || "
                f"CAST('{{\"max_input_tokens\": {max_input_tokens}}}' AS JSONB) AS JSON)"
            )
        else:
            capabilities_update = (
                f"json_set(capabilities_json, '$.max_input_tokens', {max_input_tokens})"
            )
        op.execute(
            f"""
            UPDATE provider_models
            SET capabilities_json = {capabilities_update},
                catalog_revision = '2026-07-17.1-pgpt-input-limits',
                verified_at = '2026-07-17 00:00:00+00:00'
            WHERE provider_id = 'pgpt' AND model_key = '{model_key}'
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    for model_key in _INPUT_LIMITS:
        capabilities_update = (
            "CAST(CAST(capabilities_json AS JSONB) - 'max_input_tokens' AS JSON)"
            if bind.dialect.name == "postgresql"
            else "json_remove(capabilities_json, '$.max_input_tokens')"
        )
        op.execute(
            f"""
            UPDATE provider_models
            SET capabilities_json = {capabilities_update},
                catalog_revision = '2026-07-15.1-pgpt-5.5-5.6',
                verified_at = '2026-07-15 00:00:00+00:00'
            WHERE provider_id = 'pgpt' AND model_key = '{model_key}'
            """
        )
