"""Compact standard context at 85 percent of the 272K price boundary.

Revision ID: 0076
Revises: 0075
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


_POLICY_REVISION = "2026-08-06.4-standard-context-85pct"
_MODELS = (
    ("pgpt", "gpt-5.4", 20_000, "2026-07-29.2-standard-context-20k-headroom"),
    ("pgpt", "gpt-5.5", 20_000, "2026-07-29.2-standard-context-20k-headroom"),
    ("pgpt", "gpt-5.6-sol", 20_000, "2026-07-29.2-standard-context-20k-headroom"),
    ("pgpt", "gpt-5.6-terra", 20_000, "2026-08-06.3-gpt-5.6-pricing"),
    ("pgpt", "gpt-5.6-luna", 20_000, "2026-08-06.3-gpt-5.6-pricing"),
    ("openai", "gpt-5.6-sol", 20_000, "2026-07-29.2-standard-context-20k-headroom"),
    ("openai", "gpt-5.6-terra", 20_000, "2026-08-06.3-gpt-5.6-pricing"),
    ("openai", "gpt-5.6-luna", 20_000, "2026-08-06.3-gpt-5.6-pricing"),
    ("codex", "gpt-5.6-sol", 778_000, "2026-08-06.2-codex-5.6-token-limits"),
    ("codex", "gpt-5.6-terra", 778_000, "2026-08-06.3-gpt-5.6-pricing"),
    ("codex", "gpt-5.6-luna", 778_000, "2026-08-06.3-gpt-5.6-pricing"),
)


def _update_profile(
    *, provider_id: str, model_key: str, reserve_tokens: int, catalog_revision: str
) -> None:
    bind = op.get_bind()
    profile_json = json.dumps(
        {
            "context_compaction_threshold": 1.0,
            "standard_context_compaction_reserve_tokens": reserve_tokens,
        },
        separators=(",", ":"),
    )
    if bind.dialect.name == "postgresql":
        capabilities_update = (
            "CAST(CAST(capabilities_json AS JSONB) || "
            "CAST(:profile AS JSONB) AS JSON)"
        )
        standard_mode_filter = (
            "CAST(capabilities_json AS JSONB) ->> "
            "'context_capacity_mode' = 'standard'"
        )
    else:
        capabilities_update = "json_patch(capabilities_json, :profile)"
        standard_mode_filter = (
            "json_extract(capabilities_json, "
            "'$.context_capacity_mode') = 'standard'"
        )
    bind.execute(
        sa.text(
            f"""
            UPDATE provider_models
            SET capabilities_json = {capabilities_update},
                catalog_revision = :catalog_revision,
                verified_at = :verified_at
            WHERE provider_id = :provider_id
              AND model_key = :model_key
              AND source <> 'admin_manual'
              AND {standard_mode_filter}
            """
        ),
        {
            "profile": profile_json,
            "catalog_revision": catalog_revision,
            "verified_at": datetime(2026, 8, 6, tzinfo=UTC),
            "provider_id": provider_id,
            "model_key": model_key,
        },
    )


def upgrade() -> None:
    for provider_id, model_key, _old_reserve, _old_revision in _MODELS:
        reserve_tokens = 818_800 if provider_id == "codex" else 40_800
        _update_profile(
            provider_id=provider_id,
            model_key=model_key,
            reserve_tokens=reserve_tokens,
            catalog_revision=_POLICY_REVISION,
        )


def downgrade() -> None:
    for provider_id, model_key, old_reserve, old_revision in _MODELS:
        _update_profile(
            provider_id=provider_id,
            model_key=model_key,
            reserve_tokens=old_reserve,
            catalog_revision=old_revision,
        )
