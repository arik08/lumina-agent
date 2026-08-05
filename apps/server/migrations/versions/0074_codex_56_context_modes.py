"""Add cost-boundary and full-context modes for Codex GPT-5.6.

Revision ID: 0074
Revises: 0073
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None


_MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
_UPGRADE_PROFILE = {
    "context_window": 1_050_000,
    "context_capacity_mode": "standard",
    "context_compaction_threshold": 1.0,
    "maximum_context_window": 1_050_000,
    "maximum_context_compaction_threshold": 0.85,
    "standard_context_compaction_reserve_tokens": 778_000,
}
_DOWNGRADE_PROFILE = {
    "context_window": 272_000,
    "context_compaction_threshold": 0.85,
}


def _update_profile(*, upgrade: bool) -> None:
    bind = op.get_bind()
    profile = _UPGRADE_PROFILE if upgrade else _DOWNGRADE_PROFILE
    profile_json = json.dumps(profile, separators=(",", ":"))
    if bind.dialect.name == "postgresql":
        capabilities_update = "CAST(CAST(capabilities_json AS JSONB) || CAST(:profile AS JSONB) AS JSON)"
        if not upgrade:
            capabilities_update = (
                "CAST(((CAST(capabilities_json AS JSONB) - 'context_capacity_mode') "
                "- 'maximum_context_window' - 'maximum_context_compaction_threshold' "
                "- 'standard_context_compaction_reserve_tokens') || "
                "CAST(:profile AS JSONB) AS JSON)"
            )
    else:
        capabilities_update = "json_patch(capabilities_json, :profile)"
        if not upgrade:
            capabilities_update = (
                "json_patch(json_remove(capabilities_json, '$.context_capacity_mode', "
                "'$.maximum_context_window', '$.maximum_context_compaction_threshold', "
                "'$.standard_context_compaction_reserve_tokens'), :profile)"
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
                "2026-08-06.1-codex-5.6-context-modes"
                if upgrade
                else "2026-08-05.1-codex-oauth-5.6"
            ),
            "verified_at": datetime(2026, 8, 6 if upgrade else 5, tzinfo=UTC),
        },
    )


def upgrade() -> None:
    _update_profile(upgrade=True)


def downgrade() -> None:
    _update_profile(upgrade=False)
