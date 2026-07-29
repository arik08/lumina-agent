"""Leave 20K input headroom in standard context mode.

Revision ID: 0068
Revises: 0067
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


_MODELS = (
    ("pgpt", "gpt-5.4"),
    ("pgpt", "gpt-5.5"),
    ("pgpt", "gpt-5.6-sol"),
    ("pgpt", "gpt-5.6-terra"),
    ("pgpt", "gpt-5.6-luna"),
    ("openai", "gpt-5.6-sol"),
    ("openai", "gpt-5.6-terra"),
    ("openai", "gpt-5.6-luna"),
)


def _update_standard_profile(
    *,
    provider_id: str,
    model_key: str,
    threshold: float,
    catalog_revision: str,
) -> None:
    bind = op.get_bind()
    profile: dict[str, object] = {"context_compaction_threshold": threshold}
    if threshold == 1.0:
        profile["standard_context_compaction_reserve_tokens"] = 20_000
    profile_json = json.dumps(profile, separators=(",", ":"))
    if bind.dialect.name == "postgresql":
        if threshold == 1.0:
            capabilities_update = (
                "CAST(CAST(capabilities_json AS JSONB) || "
                "CAST(:profile AS JSONB) AS JSON)"
            )
        else:
            capabilities_update = (
                "CAST((CAST(capabilities_json AS JSONB) - "
                "'standard_context_compaction_reserve_tokens') || "
                "CAST(:profile AS JSONB) AS JSON)"
            )
        standard_mode_filter = (
            "CAST(capabilities_json AS JSONB) ->> "
            "'context_capacity_mode' = 'standard'"
        )
    else:
        if threshold == 1.0:
            capabilities_update = "json_patch(capabilities_json, :profile)"
        else:
            capabilities_update = (
                "json_patch(json_remove(capabilities_json, "
                "'$.standard_context_compaction_reserve_tokens'), :profile)"
            )
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
                verified_at = '2026-07-29 00:00:00+00:00'
            WHERE provider_id = :provider_id
              AND model_key = :model_key
              AND source <> 'admin_manual'
              AND {standard_mode_filter}
            """
        ),
        {
            "profile": profile_json,
            "catalog_revision": catalog_revision,
            "provider_id": provider_id,
            "model_key": model_key,
        },
    )


def upgrade() -> None:
    for provider_id, model_key in _MODELS:
        _update_standard_profile(
            provider_id=provider_id,
            model_key=model_key,
            threshold=1.0,
            catalog_revision="2026-07-29.2-standard-context-20k-headroom",
        )


def downgrade() -> None:
    for provider_id, model_key in _MODELS:
        _update_standard_profile(
            provider_id=provider_id,
            model_key=model_key,
            threshold=0.85,
            catalog_revision="2026-07-29.1-standard-context-mode",
        )
