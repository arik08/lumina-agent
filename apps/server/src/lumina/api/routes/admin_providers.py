from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...audit import record_audit
from ...authorization import require_admin
from ...config import Settings, get_settings
from ...db import get_db
from ...models import ProviderModel
from ...providers import ProviderConfigurationError, ProviderRequestError
from ...providers.catalog import (
    DEFAULT_CONTEXT_COMPACTION_THRESHOLD,
    ModelCatalogSeed,
    catalog_model,
    initial_model_catalog,
)
from ...providers.openai_compatible import OpenAICompatibleAdapter
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem
from ..schemas import ApiModel
from .providers import PROVIDER_NAMES


router = APIRouter(prefix="/admin/providers", tags=["admin", "providers"])


class ProviderModelCreate(ApiModel):
    model_key: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=240)
    runtime_model_id: str = Field(min_length=1, max_length=240)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    enabled: bool = False
    is_default: bool = False
    sort_order: int = Field(default=100, ge=0, le=100_000)
    capabilities: dict[str, Any] = Field(default_factory=dict)


class ProviderModelPatch(ApiModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=240)
    runtime_model_id: str | None = Field(default=None, min_length=1, max_length=240)
    aliases: list[str] | None = Field(default=None, max_length=30)
    enabled: bool | None = None
    is_default: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    capabilities: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "ProviderModelPatch":
        if not self.model_fields_set:
            raise ValueError("At least one model field is required")
        return self


class ProviderAvailabilityPatch(ApiModel):
    enabled: bool


def _payload(model: ProviderModel) -> dict[str, Any]:
    catalog_entry = catalog_model(model.provider_id, model.model_key)
    hard_max = _positive_int(
        catalog_entry.capabilities.max_output_tokens
        if catalog_entry
        else model.capabilities_json.get(
            "max_output_tokens", model.capabilities_json.get("maxOutputTokens")
        )
    )
    default_max = _positive_int(
        catalog_entry.default_max_output_tokens if catalog_entry else None
    )
    configured_max = _positive_int(
        model.capabilities_json.get(
            "configured_max_output_tokens",
            model.capabilities_json.get("configuredMaxOutputTokens"),
        )
    )
    if configured_max is None or (hard_max is not None and configured_max > hard_max):
        configured_max = default_max
    return {
        "providerId": model.provider_id,
        "modelKey": model.model_key,
        "displayName": model.display_name,
        "runtimeModelId": model.runtime_model_id,
        "aliases": model.aliases_json,
        "enabled": model.enabled,
        "isDefault": model.is_default,
        "sortOrder": model.sort_order,
        "capabilities": model.capabilities_json,
        "defaultContextWindow": (
            catalog_entry.capabilities.context_window if catalog_entry else None
        ),
        "defaultContextUsageRatio": (
            catalog_entry.context_compaction_threshold
            if catalog_entry and catalog_entry.context_compaction_threshold is not None
            else DEFAULT_CONTEXT_COMPACTION_THRESHOLD
        ),
        "maxOutputTokens": hard_max,
        "defaultMaxOutputTokens": default_max,
        "configuredMaxOutputTokens": configured_max,
        "outputTokenStep": catalog_entry.output_token_step if catalog_entry else 1_000,
        "source": model.source,
        "catalogRevision": model.catalog_revision,
        "verifiedAt": model.verified_at,
    }


def _validate_capabilities(
    capabilities: dict[str, Any], *, catalog_entry: ModelCatalogSeed | None = None
) -> None:
    context_window = capabilities.get("context_window", capabilities.get("contextWindow"))
    if context_window is not None and (
        isinstance(context_window, bool)
        or not isinstance(context_window, int)
        or context_window < 1
    ):
        raise ApiProblem(
            422,
            "invalid_model_context_window",
            "최대 컨텍스트 토큰은 1 이상의 정수여야 합니다.",
        )
    context_usage_ratio = capabilities.get(
        "context_compaction_threshold",
        capabilities.get("contextCompactionThreshold"),
    )
    if context_usage_ratio is not None and (
        isinstance(context_usage_ratio, bool)
        or not isinstance(context_usage_ratio, (int, float))
        or not 0 < context_usage_ratio <= 1
    ):
        raise ApiProblem(
            422,
            "invalid_context_usage_ratio",
            "실제 사용 가능 비율은 1% 이상 100% 이하이어야 합니다.",
        )
    stored_hard_max = capabilities.get(
        "max_output_tokens", capabilities.get("maxOutputTokens")
    )
    if stored_hard_max is not None and _positive_int(stored_hard_max) is None:
        raise ApiProblem(
            422,
            "invalid_model_output_token_limit",
            "모델 최대 출력 토큰은 1 이상의 정수여야 합니다.",
        )
    configured_max = capabilities.get(
        "configured_max_output_tokens",
        capabilities.get("configuredMaxOutputTokens"),
    )
    if configured_max is None:
        return
    configured_max = _positive_int(configured_max)
    if configured_max is None:
        raise ApiProblem(
            422,
            "invalid_model_output_token_limit",
            "출력 토큰 상한은 1 이상의 정수여야 합니다.",
        )
    hard_max = _positive_int(
        catalog_entry.capabilities.max_output_tokens
        if catalog_entry
        else stored_hard_max
    )
    if hard_max is not None and configured_max > hard_max:
        raise ApiProblem(
            422,
            "model_output_token_limit_exceeded",
            f"출력 토큰 상한은 이 모델의 최대값 {hard_max:,} 토큰을 넘을 수 없습니다.",
        )


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _provider_payload(provider_id: str, models: list[ProviderModel]) -> dict[str, Any]:
    return {
        "id": provider_id,
        "displayName": PROVIDER_NAMES.get(provider_id, provider_id),
        "enabled": any(model.enabled for model in models),
        "enabledModelCount": sum(1 for model in models if model.enabled),
        "modelCount": len(models),
    }


@router.get("")
def list_admin_providers(
    actor=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_admin(actor)
    models = list(
        db.scalars(
            select(ProviderModel).order_by(
                ProviderModel.provider_id,
                ProviderModel.sort_order,
                ProviderModel.model_key,
            )
        )
    )
    grouped: dict[str, list[ProviderModel]] = {}
    for model in models:
        grouped.setdefault(model.provider_id, []).append(model)
    return [_provider_payload(provider_id, items) for provider_id, items in grouped.items()]


@router.patch("/{provider_id}")
def patch_provider_availability(
    provider_id: str,
    payload: ProviderAvailabilityPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(context.user)
    models = list(
        db.scalars(
            select(ProviderModel)
            .where(ProviderModel.provider_id == provider_id)
            .order_by(ProviderModel.sort_order, ProviderModel.model_key)
        )
    )
    if not models:
        raise ApiProblem(404, "not_found", "Provider를 찾을 수 없습니다.")

    if payload.enabled:
        enabled_models = [model for model in models if model.enabled]
        if not enabled_models:
            preferred = next(
                (
                    model
                    for model in models
                    if (entry := catalog_model(provider_id, model.model_key))
                    and entry.is_default
                ),
                models[0],
            )
            preferred.enabled = True
            enabled_models = [preferred]
        default_model = next(
            (model for model in enabled_models if model.is_default), enabled_models[0]
        )
        for model in models:
            model.is_default = model.id == default_model.id
    else:
        for model in models:
            model.enabled = False
            model.is_default = False

    record_audit(
        db,
        action="provider_availability_updated",
        target_type="provider",
        target_id=provider_id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"enabled": payload.enabled},
    )
    db.commit()
    return _provider_payload(provider_id, models)


@router.get("/{provider_id}/models")
def list_admin_models(
    provider_id: str,
    actor=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_admin(actor)
    models = db.scalars(
        select(ProviderModel)
        .where(ProviderModel.provider_id == provider_id)
        .order_by(ProviderModel.sort_order, ProviderModel.model_key)
    )
    return [_payload(model) for model in models]


@router.post("/{provider_id}/models/discover")
async def discover_models(
    provider_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Compare the reviewed catalog with DB state without activating discoveries."""
    require_admin(context.user)
    persisted = {
        model.model_key: model
        for model in db.scalars(
            select(ProviderModel).where(ProviderModel.provider_id == provider_id)
        )
    }
    if provider_id == "openai_compatible":
        items = await _discover_openai_compatible(settings, persisted)
    else:
        items = []
        for candidate in initial_model_catalog(provider_id):
            current = persisted.get(candidate.model_key)
            items.append(
                {
                    "modelKey": candidate.model_key,
                    "displayName": candidate.display_name,
                    "runtimeModelId": candidate.runtime_model_id,
                    "catalogRevision": candidate.catalog_revision,
                    "source": candidate.source,
                    "status": "active"
                    if current and current.enabled
                    else "registered"
                    if current
                    else "discovered",
                    "activationRequired": not bool(current and current.enabled),
                }
            )
    record_audit(
        db,
        action="provider_models_discovered",
        target_type="provider",
        target_id=provider_id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"candidate_count": len(items), "activated_count": 0},
    )
    db.commit()
    return {
        "providerId": provider_id,
        "items": items,
        "autoActivated": False,
    }


async def _discover_openai_compatible(
    settings: Settings, persisted: dict[str, ProviderModel]
) -> list[dict[str, Any]]:
    api_key = settings.openai_compatible_api_key
    base_url = settings.openai_compatible_base_url
    if (
        api_key is None
        or not api_key.get_secret_value().strip()
        or base_url is None
        or not base_url.strip()
    ):
        raise ApiProblem(
            409,
            "provider_needs_setup",
            "OpenAI Compatible Provider 연결 설정이 필요합니다.",
        )
    try:
        adapter = OpenAICompatibleAdapter(
            provider_id="openai_compatible",
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
        )
        candidates = await adapter.discover_models()
    except ProviderConfigurationError as exc:
        raise ApiProblem(
            409,
            "provider_needs_setup",
            "OpenAI Compatible Provider 연결 설정이 올바르지 않습니다.",
        ) from exc
    except ProviderRequestError as exc:
        raise ApiProblem(
            502,
            "provider_discovery_failed",
            "OpenAI Compatible Model 후보를 조회할 수 없습니다.",
            details={"stage": exc.stage, "retryable": exc.retryable},
        ) from exc

    by_runtime_id = {model.runtime_model_id: model for model in persisted.values()}
    items: list[dict[str, Any]] = []
    for runtime_model_id in candidates:
        current = persisted.get(runtime_model_id) or by_runtime_id.get(runtime_model_id)
        items.append(
            {
                "modelKey": current.model_key if current else runtime_model_id,
                "displayName": current.display_name if current else runtime_model_id,
                "runtimeModelId": runtime_model_id,
                "catalogRevision": current.catalog_revision if current else None,
                "source": "remote_models_candidate",
                "status": "active"
                if current and current.enabled
                else "registered"
                if current
                else "discovered",
                "activationRequired": not bool(current and current.enabled),
            }
        )
    return items


@router.post("/{provider_id}/models", status_code=201)
def create_model(
    provider_id: str,
    payload: ProviderModelCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(context.user)
    _validate_capabilities(
        payload.capabilities,
        catalog_entry=catalog_model(provider_id, payload.model_key),
    )
    existing = db.scalar(
        select(ProviderModel.id).where(
            ProviderModel.provider_id == provider_id,
            ProviderModel.model_key == payload.model_key,
        )
    )
    if existing is not None:
        raise ApiProblem(409, "model_already_exists", "이미 등록된 Model입니다.")
    if payload.is_default and not payload.enabled:
        raise ApiProblem(
            422, "default_model_must_be_enabled", "기본 Model은 활성 상태여야 합니다."
        )
    if payload.is_default:
        db.execute(
            update(ProviderModel)
            .where(ProviderModel.provider_id == provider_id)
            .values(is_default=False)
        )
    now = datetime.now(UTC)
    model = ProviderModel(
        provider_id=provider_id,
        model_key=payload.model_key,
        display_name=payload.display_name,
        runtime_model_id=payload.runtime_model_id,
        aliases_json=_normalized_aliases(payload.aliases),
        enabled=payload.enabled,
        is_default=payload.is_default,
        sort_order=payload.sort_order,
        capabilities_json=payload.capabilities,
        source="admin_manual",
        catalog_revision=f"admin-{now.date().isoformat()}",
        verified_at=now,
    )
    db.add(model)
    db.flush()
    record_audit(
        db,
        action="provider_model_registered",
        target_type="provider_model",
        target_id=model.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={
            "provider_id": provider_id,
            "model_key": model.model_key,
            "enabled": model.enabled,
        },
    )
    db.commit()
    return _payload(model)


@router.patch("/{provider_id}/models/{model_key}")
def patch_model(
    provider_id: str,
    model_key: str,
    payload: ProviderModelPatch,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(context.user)
    model = db.scalar(
        select(ProviderModel).where(
            ProviderModel.provider_id == provider_id,
            ProviderModel.model_key == model_key,
        )
    )
    if model is None:
        raise ApiProblem(404, "not_found", "Model을 찾을 수 없습니다.")
    values = payload.model_dump(exclude_unset=True)
    enabled = values.get("enabled", model.enabled)
    becoming_default = values.get("is_default") is True
    if values.get("enabled") is True and not db.scalar(
        select(ProviderModel.id).where(
            ProviderModel.provider_id == provider_id,
            ProviderModel.enabled.is_(True),
            ProviderModel.is_default.is_(True),
        )
    ):
        values["is_default"] = True
        becoming_default = True
    if becoming_default and not enabled:
        raise ApiProblem(
            422, "default_model_must_be_enabled", "기본 Model은 활성 상태여야 합니다."
        )
    if values.get("is_default") is False and model.is_default:
        other_default = db.scalar(
            select(ProviderModel.id).where(
                ProviderModel.provider_id == provider_id,
                ProviderModel.model_key != model_key,
                ProviderModel.is_default.is_(True),
                ProviderModel.enabled.is_(True),
            )
        )
        if other_default is None:
            raise ApiProblem(
                409,
                "provider_default_required",
                "다른 기본 Model을 먼저 지정해 주세요.",
            )
    if values.get("enabled") is False and model.is_default and not becoming_default:
        replacement = db.scalar(
            select(ProviderModel).where(
                ProviderModel.provider_id == provider_id,
                ProviderModel.model_key != model_key,
                ProviderModel.enabled.is_(True),
            ).order_by(ProviderModel.sort_order, ProviderModel.model_key)
        )
        model.is_default = False
        if replacement is not None:
            replacement.is_default = True
    if becoming_default:
        db.execute(
            update(ProviderModel)
            .where(
                ProviderModel.provider_id == provider_id,
                ProviderModel.id != model.id,
            )
            .values(is_default=False)
        )
    for field in (
        "display_name",
        "runtime_model_id",
        "enabled",
        "is_default",
        "sort_order",
    ):
        if field in values:
            setattr(model, field, values[field])
    if "aliases" in values:
        model.aliases_json = _normalized_aliases(values["aliases"])
    if "capabilities" in values:
        _validate_capabilities(
            values["capabilities"],
            catalog_entry=catalog_model(provider_id, model_key),
        )
        model.capabilities_json = values["capabilities"]
    model.source = "admin_manual"
    model.catalog_revision = f"admin-{datetime.now(UTC).date().isoformat()}"
    model.verified_at = datetime.now(UTC)
    record_audit(
        db,
        action="provider_model_updated",
        target_type="provider_model",
        target_id=model.id,
        result="success",
        actor=context.user,
        request_id=getattr(request.state, "request_id", None),
        metadata={"changed_fields": sorted(values), "model_key": model.model_key},
    )
    db.commit()
    return _payload(model)


def _normalized_aliases(values: list[str]) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for value in values:
        alias = value.strip()
        if not alias or alias.casefold() in seen:
            continue
        seen.add(alias.casefold())
        aliases.append(alias)
    return aliases
