"""Default long-context models to the standard 272K capacity mode.

Revision ID: 0067
Revises: 0066
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


_MODELS = {
    "pgpt": {
        "gpt-5.4": 911_900,
        "gpt-5.5": 911_900,
        "gpt-5.6-sol": None,
        "gpt-5.6-terra": None,
        "gpt-5.6-luna": None,
    },
    "openai": {
        "gpt-5.6-sol": None,
        "gpt-5.6-terra": None,
        "gpt-5.6-luna": None,
    },
}


def _merge_profile(provider_id: str, model_key: str, profile: dict[str, object]) -> None:
    bind = op.get_bind()
    profile_json = json.dumps(profile, separators=(",", ":"))
    if bind.dialect.name == "postgresql":
        capabilities_update = (
            "CAST(CAST(capabilities_json AS JSONB) || "
            "CAST(:profile AS JSONB) AS JSON)"
        )
    else:
        capabilities_update = "json_patch(capabilities_json, :profile)"
    bind.execute(
        sa.text(
            f"""
            UPDATE provider_models
            SET capabilities_json = {capabilities_update},
                catalog_revision = '2026-07-29.1-standard-context-mode',
                verified_at = '2026-07-29 00:00:00+00:00'
            WHERE provider_id = :provider_id
              AND model_key = :model_key
              AND source <> 'admin_manual'
            """
        ),
        {
            "profile": profile_json,
            "provider_id": provider_id,
            "model_key": model_key,
        },
    )


def upgrade() -> None:
    for provider_id, models in _MODELS.items():
        for model_key, maximum_input_tokens in models.items():
            profile: dict[str, object] = {
                "context_window": 272_000,
                "context_compaction_threshold": 0.85,
                "context_capacity_mode": "standard",
                "maximum_context_window": 1_050_000,
                "maximum_context_compaction_threshold": 0.75,
            }
            if provider_id == "pgpt" and maximum_input_tokens is not None:
                profile["max_input_tokens"] = 272_000
                profile["maximum_input_tokens"] = maximum_input_tokens
            _merge_profile(provider_id, model_key, profile)


def downgrade() -> None:
    bind = op.get_bind()
    for provider_id, models in _MODELS.items():
        for model_key, maximum_input_tokens in models.items():
            if bind.dialect.name == "postgresql":
                capabilities_update = (
                    "CAST((CAST(capabilities_json AS JSONB) - "
                    "'context_capacity_mode' - 'maximum_context_window' - "
                    "'maximum_input_tokens' - "
                    "'maximum_context_compaction_threshold' - "
                    "'context_compaction_threshold') || "
                    "CAST(:legacy AS JSONB) AS JSON)"
                )
            else:
                capabilities_update = (
                    "json_patch(json_remove(capabilities_json, "
                    "'$.context_capacity_mode', '$.maximum_context_window', "
                    "'$.maximum_input_tokens', "
                    "'$.maximum_context_compaction_threshold', "
                    "'$.context_compaction_threshold'), :legacy)"
                )
            legacy: dict[str, object] = {"context_window": 1_050_000}
            if provider_id == "pgpt" and maximum_input_tokens is not None:
                legacy["max_input_tokens"] = maximum_input_tokens
            bind.execute(
                sa.text(
                    f"""
                    UPDATE provider_models
                    SET capabilities_json = {capabilities_update},
                        catalog_revision = '2026-07-17.1-pgpt-input-limits',
                        verified_at = '2026-07-17 00:00:00+00:00'
                    WHERE provider_id = :provider_id
                      AND model_key = :model_key
                      AND source <> 'admin_manual'
                    """
                ),
                {
                    "legacy": json.dumps(legacy, separators=(",", ":")),
                    "provider_id": provider_id,
                    "model_key": model_key,
                },
            )
