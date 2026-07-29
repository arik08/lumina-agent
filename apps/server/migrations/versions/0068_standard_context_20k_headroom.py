"""Leave 20K input headroom in standard context mode.

Revision ID: 0068
Revises: 0067
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op


revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


_MODELS = {
    ("pgpt", "gpt-5.4"),
    ("pgpt", "gpt-5.5"),
    ("pgpt", "gpt-5.6-sol"),
    ("pgpt", "gpt-5.6-terra"),
    ("pgpt", "gpt-5.6-luna"),
    ("openai", "gpt-5.6-sol"),
    ("openai", "gpt-5.6-terra"),
    ("openai", "gpt-5.6-luna"),
}


def _update_standard_profiles(
    *,
    threshold: float,
    catalog_revision: str,
) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, provider_id, model_key, capabilities_json
            FROM provider_models
            WHERE source <> 'admin_manual'
            """
        )
    ).mappings()
    for row in rows:
        if (row["provider_id"], row["model_key"]) not in _MODELS:
            continue
        raw_capabilities = row["capabilities_json"]
        capabilities: dict[str, Any] = (
            json.loads(raw_capabilities)
            if isinstance(raw_capabilities, str)
            else dict(raw_capabilities or {})
        )
        if capabilities.get("context_capacity_mode") != "standard":
            continue
        capabilities["context_compaction_threshold"] = threshold
        if threshold == 1.0:
            capabilities["standard_context_compaction_reserve_tokens"] = 20_000
        else:
            capabilities.pop("standard_context_compaction_reserve_tokens", None)
        bind.execute(
            sa.text(
                """
                UPDATE provider_models
                SET capabilities_json = :capabilities,
                    catalog_revision = :catalog_revision,
                    verified_at = '2026-07-29 00:00:00+00:00'
                WHERE id = :model_id
                """
            ),
            {
                "capabilities": json.dumps(capabilities, separators=(",", ":")),
                "catalog_revision": catalog_revision,
                "model_id": row["id"],
            },
        )


def upgrade() -> None:
    _update_standard_profiles(
        threshold=1.0,
        catalog_revision="2026-07-29.2-standard-context-20k-headroom",
    )


def downgrade() -> None:
    _update_standard_profiles(
        threshold=0.85,
        catalog_revision="2026-07-29.1-standard-context-mode",
    )
