from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Organization,
    ProjectSetting,
    ProviderModel,
    ScheduledTask,
    UserSetting,
)
from .catalog import application_default_execution


DEFAULT_FALLBACK_EFFORT = "medium"


def enabled_provider_model(
    db: Session,
    provider_id: str,
    *,
    preferred_model_key: str | None = None,
) -> ProviderModel | None:
    """Return the requested enabled model or the provider's enabled default."""
    if preferred_model_key is not None:
        preferred = db.scalar(
            select(ProviderModel).where(
                ProviderModel.provider_id == provider_id,
                ProviderModel.model_key == preferred_model_key,
                ProviderModel.enabled.is_(True),
            )
        )
        if preferred is not None:
            return preferred
    default = db.scalar(
        select(ProviderModel).where(
            ProviderModel.provider_id == provider_id,
            ProviderModel.enabled.is_(True),
            ProviderModel.is_default.is_(True),
        )
    )
    if default is not None:
        return default
    return db.scalars(
        select(ProviderModel)
        .where(
            ProviderModel.provider_id == provider_id,
            ProviderModel.enabled.is_(True),
        )
        .order_by(ProviderModel.sort_order, ProviderModel.model_key)
    ).first()


def application_default_model(
    db: Session,
    *,
    environment: str,
) -> ProviderModel | None:
    """Resolve the application default to an enabled catalog model when possible."""
    provider_id, model_key, _effort_id = application_default_execution(environment)
    if provider_id != "mock":
        model = enabled_provider_model(
            db,
            provider_id,
            preferred_model_key=model_key,
        )
        if model is not None:
            return model
    return db.scalars(
        select(ProviderModel)
        .where(ProviderModel.enabled.is_(True))
        .order_by(
            ProviderModel.provider_id,
            ProviderModel.sort_order,
            ProviderModel.model_key,
        )
    ).first()


def default_effort_for_model(
    model: ProviderModel,
    requested_effort: object = None,
) -> str | None:
    """Use an explicit supported effort, otherwise the product fallback effort."""
    if model.capabilities_json.get("reasoning_effort") is False:
        return None
    raw_options = model.capabilities_json.get("effort_options")
    options = tuple(
        value
        for value in (raw_options if isinstance(raw_options, (list, tuple)) else ())
        if isinstance(value, str) and value
    ) or ("low", "medium", "high")
    if (
        isinstance(requested_effort, str)
        and requested_effort != "auto"
        and requested_effort in options
    ):
        return requested_effort
    if DEFAULT_FALLBACK_EFFORT in options:
        return DEFAULT_FALLBACK_EFFORT
    return options[0] if options else None


def _execution_reference_matches(
    value: object,
    *,
    provider_id: str,
    model_key: str,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    stored_provider_id = value.get("providerId", value.get("provider_id"))
    stored_model_key = value.get("modelKey", value.get("model_key"))
    return stored_provider_id == provider_id and stored_model_key == model_key


def _fallback_execution_value(
    value: object,
    *,
    provider_id: str,
    model_key: str,
    fallback_model: ProviderModel,
) -> dict[str, Any] | None:
    if not _execution_reference_matches(
        value,
        provider_id=provider_id,
        model_key=model_key,
    ):
        return None
    if not isinstance(value, Mapping):
        return None
    current: dict[str, Any] = {str(key): item for key, item in value.items()}
    current.update(
        {
            "providerId": fallback_model.provider_id,
            "modelKey": fallback_model.model_key,
            "effortId": default_effort_for_model(
                fallback_model,
                current.get("effortId", current.get("effort_id")),
            ),
        }
    )
    current.pop("provider_id", None)
    current.pop("model_key", None)
    current.pop("effort_id", None)
    return current


def rebind_disabled_model_references(
    db: Session,
    *,
    provider_id: str,
    model_key: str,
    fallback_model: ProviderModel | None,
) -> int:
    """Move future configuration references away from a disabled model.

    Run rows and their snapshots are intentionally excluded because they are the
    immutable record of the model used for that Run. This updates only settings,
    candidate lists and scheduled-task configuration used by future work.
    """
    if fallback_model is None:
        return 0
    changed = 0
    for organization in db.scalars(select(Organization)).all():
        next_value = _fallback_execution_value(
            organization.initial_execution_settings_json,
            provider_id=provider_id,
            model_key=model_key,
            fallback_model=fallback_model,
        )
        if next_value is not None:
            organization.initial_execution_settings_json = next_value
            changed += 1

    for user_default_setting in db.scalars(
        select(UserSetting).where(UserSetting.key == "execution.default")
    ).all():
        next_value = _fallback_execution_value(
            user_default_setting.value_json,
            provider_id=provider_id,
            model_key=model_key,
            fallback_model=fallback_model,
        )
        if next_value is not None:
            user_default_setting.value_json = next_value
            changed += 1

    for project_default_setting in db.scalars(
        select(ProjectSetting).where(ProjectSetting.key == "execution.default")
    ).all():
        next_value = _fallback_execution_value(
            project_default_setting.value_json,
            provider_id=provider_id,
            model_key=model_key,
            fallback_model=fallback_model,
        )
        if next_value is not None:
            project_default_setting.value_json = next_value
            changed += 1

    for candidates_setting in db.scalars(
        select(UserSetting).where(UserSetting.key == "models.candidates")
    ).all():
        if not isinstance(candidates_setting.value_json, Mapping):
            continue
        current_candidates = dict(candidates_setting.value_json)
        model_candidates = current_candidates.get(provider_id)
        if not isinstance(model_candidates, list) or model_key not in model_candidates:
            continue
        remaining = [candidate for candidate in model_candidates if candidate != model_key]
        if remaining:
            current_candidates[provider_id] = remaining
        else:
            current_candidates.pop(provider_id, None)
        candidates_setting.value_json = current_candidates
        changed += 1

    for task in db.scalars(
        select(ScheduledTask).where(
            ScheduledTask.provider_id == provider_id,
            ScheduledTask.model_key == model_key,
        )
    ).all():
        task.provider_id = fallback_model.provider_id
        task.model_key = fallback_model.model_key
        task.effort = default_effort_for_model(fallback_model, task.effort)
        changed += 1
    return changed


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
        not isinstance(effort_id, str)
        or (effort_id != "auto" and effort_id not in effort_options)
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
    if provider_id != "mock":
        fallback_model = application_default_model(db, environment=environment)
        if fallback_model is not None:
            return (
                {
                    "providerId": fallback_model.provider_id,
                    "modelKey": fallback_model.model_key,
                    "effortId": default_effort_for_model(fallback_model, effort_id),
                },
                "application",
            )
    return (
        {
            "providerId": provider_id,
            "modelKey": model_key,
            "effortId": effort_id,
        },
        "application",
    )
