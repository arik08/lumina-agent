from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...authorization import require_project
from ...config import Settings, get_settings
from ...conversations.service import default_project
from ...db import get_db
from ...models import Project, ProjectSetting, ProviderModel, User, UserSetting
from ...providers.codex import codex_oauth_available
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem
from ..schemas import SettingsPatch


router = APIRouter(tags=["providers", "settings"])

PROVIDER_NAMES = {
    "mock": "Lumina Mock",
    "pgpt": "P-GPT",
    "codex": "Codex",
    "openai": "OpenAI",
    "anthropic": "Claude",
    "google": "Gemini",
    "openai_compatible": "OpenAI Compatible",
}


def _provider_status(provider_id: str, settings: Settings) -> str:
    if provider_id == "mock":
        return "ready" if settings.environment != "production" else "unavailable"
    if provider_id == "pgpt":
        return (
            "ready"
            if all(
                _has_secret(value)
                for value in (
                    settings.pgpt_api_key,
                    settings.pgpt_employee_no,
                    settings.pgpt_company_code,
                )
            )
            else "needs_setup"
        )
    if provider_id == "codex":
        return "ready" if codex_oauth_available() else "needs_setup"
    if provider_id == "openai":
        api_key = settings.openai_api_key
        return (
            "ready"
            if _has_secret(api_key) and _valid_base_url(settings.openai_base_url)
            else "needs_setup"
        )
    if provider_id == "anthropic":
        return (
            "ready"
            if _has_secret(settings.anthropic_api_key)
            and _valid_base_url(settings.anthropic_base_url)
            else "needs_setup"
        )
    if provider_id == "google":
        return (
            "ready"
            if _has_secret(settings.google_api_key)
            and _valid_base_url(settings.google_base_url)
            else "needs_setup"
        )
    if provider_id == "openai_compatible":
        return (
            "ready"
            if _has_secret(settings.openai_compatible_api_key)
            and _valid_base_url(settings.openai_compatible_base_url)
            else "needs_setup"
        )
    return "needs_setup"


def _has_secret(value: Any) -> bool:
    return value is not None and bool(value.get_secret_value().strip())


def _valid_base_url(value: str | None) -> bool:
    if value is None:
        return False
    parsed = urlsplit(value.strip())
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


@router.get("/providers")
def get_providers(
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, object]]:
    if project_id:
        require_project(db, user, project_id)
    provider_ids = list(
        db.scalars(
            select(ProviderModel.provider_id)
            .where(ProviderModel.enabled.is_(True))
            .distinct()
            .order_by(ProviderModel.provider_id)
        )
    )
    if settings.environment != "production":
        provider_ids.insert(0, "mock")
    result: list[dict[str, object]] = []
    for provider_id in provider_ids:
        default_model = None
        if provider_id == "mock":
            default_model = "mock-agent"
        else:
            default_model = db.scalar(
                select(ProviderModel.model_key).where(
                    ProviderModel.provider_id == provider_id,
                    ProviderModel.enabled.is_(True),
                    ProviderModel.is_default.is_(True),
                )
            )
        status = _provider_status(provider_id, settings)
        result.append(
            {
                "id": provider_id,
                "displayName": PROVIDER_NAMES.get(provider_id, provider_id),
                "enabled": status == "ready",
                "connectionStatus": status,
                "defaultModelKey": default_model,
            }
        )
    return result


@router.get("/providers/{provider_id}/models")
def get_provider_models(
    provider_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    if project_id:
        require_project(db, user, project_id)
    if provider_id == "mock":
        return [
            {
                "modelKey": "mock-agent",
                "displayName": "Lumina Mock Agent",
                "enabled": True,
                "isDefault": True,
                "catalogRevision": "development",
                "capabilities": _capabilities(
                    {"tools": True, "structured_output": True}
                ),
            }
        ]
    models = list(
        db.scalars(
            select(ProviderModel)
            .where(
                ProviderModel.provider_id == provider_id,
                ProviderModel.enabled.is_(True),
            )
            .order_by(ProviderModel.sort_order, ProviderModel.model_key)
        )
    )
    return [
        {
            "modelKey": model.model_key,
            "displayName": model.display_name,
            "enabled": model.enabled,
            "isDefault": model.is_default,
            "catalogRevision": model.catalog_revision,
            "capabilities": _capabilities(model.capabilities_json),
        }
        for model in models
    ]


def _capabilities(raw: dict[str, Any]) -> dict[str, object]:
    efforts = raw.get("effort_options") or ("low", "medium", "high")
    return {
        "toolCalling": bool(raw.get("tools", raw.get("tool_calling", True))),
        "structuredOutput": bool(raw.get("structured_output", True)),
        "imageInput": bool(raw.get("image_input", False)),
        "imageGeneration": bool(raw.get("image_generation", False)),
        "contextWindow": raw.get("context_window"),
        "effortOptions": [
            {
                "id": value,
                "label": {"low": "낮음", "medium": "중간", "high": "높음"}.get(
                    value, value
                ),
            }
            for value in efforts
        ],
    }


def _setting(db: Session, user_id: str, key: str) -> UserSetting | None:
    return db.scalar(
        select(UserSetting).where(
            UserSetting.user_id == user_id, UserSetting.key == key
        )
    )


def _project_setting(db: Session, project_id: str, key: str) -> ProjectSetting | None:
    return db.scalar(
        select(ProjectSetting).where(
            ProjectSetting.project_id == project_id, ProjectSetting.key == key
        )
    )


def _resolved_settings(
    db: Session, user: User, project: Project, settings: Settings
) -> tuple[
    dict[str, Any],
    UserSetting | None,
    UserSetting | ProjectSetting | None,
    UserSetting | None,
]:
    theme_setting = _setting(db, user.id, "ui.theme")
    theme = theme_setting.value_json if theme_setting else "light"
    output_mode_key = "composer.output_mode"
    output_mode_setting = (
        _project_setting(db, project.id, output_mode_key)
        if project.project_type == "shared"
        else _setting(db, user.id, output_mode_key)
    )
    output_mode = output_mode_setting.value_json if output_mode_setting else "auto"
    execution_setting: UserSetting | ProjectSetting | None
    execution_source: str
    if project.project_type == "shared":
        execution_setting = _project_setting(db, project.id, "execution.default")
        execution_source = "project" if execution_setting else "application"
    else:
        user_default = _setting(db, user.id, "execution.default")
        execution_setting = user_default
        execution_source = "user" if user_default else "application"
    if execution_setting:
        execution = dict(execution_setting.value_json)
    elif settings.environment != "production":
        execution = {
            "providerId": "mock",
            "modelKey": "mock-agent",
            "effortId": "medium",
        }
    else:
        execution = {"providerId": "pgpt", "modelKey": "gpt-5.4", "effortId": "medium"}
    model_candidates_setting = _setting(db, user.id, "models.candidates")
    model_candidates = (
        dict(model_candidates_setting.value_json)
        if model_candidates_setting
        else _default_model_candidates(db)
    )
    result: dict[str, Any] = {
        "theme": theme if theme in {"light", "dark"} else "light",
        "outputMode": output_mode
        if output_mode in {"auto", "chat", "file"}
        else "auto",
        "execution": execution,
        "modelCandidates": model_candidates,
        "source": {"theme": "user", "execution": execution_source},
        "warnings": [],
    }
    result["revision"] = _settings_revision(
        result, theme_setting, execution_setting, model_candidates_setting
    )
    return result, theme_setting, execution_setting, model_candidates_setting


def _default_model_candidates(db: Session) -> dict[str, list[str]]:
    rows = db.execute(
        select(ProviderModel.provider_id, ProviderModel.model_key)
        .where(
            ProviderModel.enabled.is_(True),
            ProviderModel.provider_id.in_(("codex", "pgpt")),
        )
        .order_by(
            ProviderModel.provider_id,
            ProviderModel.sort_order,
            ProviderModel.model_key,
        )
    )
    result: dict[str, list[str]] = {}
    for provider_id, model_key in rows:
        result.setdefault(provider_id, []).append(model_key)
    return result


def _settings_revision(
    value: dict[str, Any],
    theme: UserSetting | None,
    execution: UserSetting | ProjectSetting | None,
    model_candidates: UserSetting | None,
) -> str:
    payload = {
        "value": value,
        "theme_updated": theme.updated_at.isoformat() if theme else None,
        "execution_updated": execution.updated_at.isoformat() if execution else None,
        "model_candidates_updated": (
            model_candidates.updated_at.isoformat() if model_candidates else None
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    ).hexdigest()[:24]


@router.get("/settings/current")
def get_current_settings(
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    project = (
        require_project(db, user, project_id)
        if project_id
        else default_project(db, user)
    )
    result, _theme, _execution, _model_candidates = _resolved_settings(
        db, user, project, settings
    )
    return result


@router.patch("/settings/current")
def patch_current_settings(
    payload: SettingsPatch,
    project_id: str | None = None,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    project = (
        require_project(db, context.user, project_id, write=True)
        if project_id
        else default_project(db, context.user)
    )
    current, theme_setting, execution_setting, model_candidates_setting = (
        _resolved_settings(db, context.user, project, settings)
    )
    if current["revision"] != payload.expected_revision:
        raise ApiProblem(
            409, "settings_revision_conflict", "설정이 다른 곳에서 변경되었습니다."
        )
    if payload.theme is not None:
        if theme_setting is None:
            theme_setting = UserSetting(
                user_id=context.user.id, key="ui.theme", value_json=payload.theme
            )
            db.add(theme_setting)
        else:
            theme_setting.value_json = payload.theme
    if payload.output_mode is not None:
        key = "composer.output_mode"
        if project.project_type == "shared":
            output_target = _project_setting(db, project.id, key)
            if output_target is None:
                output_target = ProjectSetting(
                    project_id=project.id,
                    key=key,
                    value_json=payload.output_mode,
                    updated_by_user_id=context.user.id,
                )
                db.add(output_target)
            else:
                output_target.value_json = payload.output_mode
                output_target.updated_by_user_id = context.user.id
        else:
            output_target = _setting(db, context.user.id, key)
            if output_target is None:
                output_target = UserSetting(
                    user_id=context.user.id, key=key, value_json=payload.output_mode
                )
                db.add(output_target)
            else:
                output_target.value_json = payload.output_mode
    if payload.execution is not None:
        value = payload.execution.model_dump(mode="json", by_alias=True)
        _validate_execution(db, value, settings)
        target: UserSetting | ProjectSetting | None
        if project.project_type == "shared":
            target = _project_setting(db, project.id, "execution.default")
            if target is None:
                target = ProjectSetting(
                    project_id=project.id,
                    key="execution.default",
                    value_json=value,
                    updated_by_user_id=context.user.id,
                )
                db.add(target)
            else:
                target.value_json = value
                target.updated_by_user_id = context.user.id
        else:
            target = _setting(db, context.user.id, "execution.default")
            if target is None:
                target = UserSetting(
                    user_id=context.user.id, key="execution.default", value_json=value
                )
                db.add(target)
            else:
                target.value_json = value
    if payload.model_candidates is not None:
        value = _validate_model_candidates(db, payload.model_candidates)
        if model_candidates_setting is None:
            model_candidates_setting = UserSetting(
                user_id=context.user.id,
                key="models.candidates",
                value_json=value,
            )
            db.add(model_candidates_setting)
        else:
            model_candidates_setting.value_json = value
    db.commit()
    result, _theme, _execution, _model_candidates = _resolved_settings(
        db, context.user, project, settings
    )
    return result


def _validate_model_candidates(
    db: Session, candidates: dict[str, list[str]]
) -> dict[str, list[str]]:
    enabled_pairs = set(
        db.execute(
            select(ProviderModel.provider_id, ProviderModel.model_key).where(
                ProviderModel.enabled.is_(True)
            )
        )
    )
    normalized: dict[str, list[str]] = {}
    for provider_id, model_keys in candidates.items():
        unique_keys = list(dict.fromkeys(model_keys))
        if any(
            (provider_id, model_key) not in enabled_pairs for model_key in unique_keys
        ):
            raise ApiProblem(
                409,
                "model_candidate_unavailable",
                "사용할 수 없는 모델은 후보에 추가할 수 없습니다.",
            )
        if unique_keys:
            normalized[provider_id] = unique_keys
    return normalized


def _validate_execution(db: Session, value: dict[str, Any], settings: Settings) -> None:
    provider_id = value.get("providerId")
    model_key = value.get("modelKey")
    if (
        provider_id == "mock"
        and settings.environment != "production"
        and model_key == "mock-agent"
    ):
        return
    if (
        not isinstance(provider_id, str)
        or _provider_status(provider_id, settings) != "ready"
    ):
        raise ApiProblem(
            409,
            "provider_needs_setup",
            "선택한 Provider의 연결 설정이 완료되지 않았습니다.",
        )
    model = db.scalar(
        select(ProviderModel.id).where(
            ProviderModel.provider_id == provider_id,
            ProviderModel.model_key == model_key,
            ProviderModel.enabled.is_(True),
        )
    )
    if model is None:
        raise ApiProblem(409, "model_unavailable", "선택한 모델을 사용할 수 없습니다.")
