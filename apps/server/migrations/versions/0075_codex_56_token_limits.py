"""Register reviewed Codex GPT-5.6 input and output limits.

Revision ID: 0075
Revises: 0074
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


_MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
_UPGRADE_PROFILE = {
    "max_input_tokens": 922_000,
    "max_output_tokens": 128_000,
    "maximum_input_tokens": 922_000,
}


def _update_profile(*, upgrade: bool) -> None:
    bind = op.get_bind()
    if upgrade:
        profile_json = json.dumps(_UPGRADE_PROFILE, separators=(",", ":"))
        if bind.dialect.name == "postgresql":
            capabilities_update = (
                "CAST(CAST(capabilities_json AS JSONB) || "
                "CAST(:profile AS JSONB) AS JSON)"
            )
        else:
            capabilities_update = "json_patch(capabilities_json, :profile)"
    else:
        profile_json = "{}"
        if bind.dialect.name == "postgresql":
            capabilities_update = (
                "CAST(CAST(capabilities_json AS JSONB) - 'max_input_tokens' "
                "- 'max_output_tokens' - 'maximum_input_tokens' AS JSON)"
            )
        else:
            capabilities_update = (
                "json_remove(capabilities_json, '$.max_input_tokens', "
                "'$.max_output_tokens', '$.maximum_input_tokens')"
            )
    bind.execute(
        sa.text(
            f"""
            UPDATE provider_models
            SET capabilities_json = {capabilities_update},
                catalog_revision = :catalog_revision,
                verified_at = :verified_at
            WHERE provider_id = 'codex'
              AND model_key IN ('gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna')
              AND source <> 'admin_manual'
            """
        ),
        {
            "profile": profile_json,
            "catalog_revision": (
                "2026-08-06.2-codex-5.6-token-limits"
                if upgrade
                else "2026-08-06.1-codex-5.6-context-modes"
            ),
            "verified_at": datetime(2026, 8, 6, tzinfo=UTC),
        },
    )


def upgrade() -> None:
    _update_profile(upgrade=True)


def downgrade() -> None:
    _update_profile(upgrade=False)
