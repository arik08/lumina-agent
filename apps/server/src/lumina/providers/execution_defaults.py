from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Organization, ProviderModel
from .catalog import application_default_execution


def normalize_initial_execution(
    db: Session,
    value: object,
    *,
    environment: str,
) -> dict[str, str | None] | None:
    if not isinstance(value, Mapping):
        return None
    provider_id = value.get("providerId", value.get("provider_id"))
    model_key = value.get("modelKey", value.get("model_key"))
    effort_id = value.get("effortId", value.get("effort_id"))
    if not isinstance(provider_id, str) or not isinstance(model_key, str):
        return None
    if environment == "production" and provider_id == "mock":
        return None
    model = db.scalar(
        select(ProviderModel).where(
            ProviderModel.provider_id == provider_id,
            ProviderModel.model_key == model_key,
            ProviderModel.enabled.is_(True),
        )
    )
    if model is None:
        return None
    effort_options = model.capabilities_json.get("effort_options") or (
        "low",
        "medium",
        "high",
    )
    if effort_id is not None and (
        not isinstance(effort_id, str) or effort_id not in effort_options
    ):
        return None
    return {
        "providerId": provider_id,
        "modelKey": model_key,
        "effortId": effort_id,
    }


def initial_execution_selection(
    db: Session,
    *,
    organization_id: str,
    environment: str,
) -> tuple[dict[str, str | None], str]:
    organization = db.get(Organization, organization_id)
    configured = normalize_initial_execution(
        db,
        organization.initial_execution_settings_json if organization else None,
        environment=environment,
    )
    if configured is not None:
        return configured, "organization"
    provider_id, model_key, effort_id = application_default_execution(environment)
    return (
        {
            "providerId": provider_id,
            "modelKey": model_key,
            "effortId": effort_id,
        },
        "application",
    )
