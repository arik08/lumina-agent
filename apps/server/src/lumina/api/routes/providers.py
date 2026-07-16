from __future__ import annotations

import hashlib
import json
from typing import Any, NoReturn
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...authorization import require_project
from ...config import Settings, get_settings
from ...conversations.service import default_project
from ...db import get_db
from ...models import Project, ProjectSetting, ProviderModel, User, UserSetting
from ...providers.codex import codex_oauth_available
from ...providers.execution_defaults import initial_execution_selection
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import ApiProblem
from ..schemas import SettingsPatch


router = APIRouter(tags=["providers", "settings"])

_USER_SETTINGS_FIELDS = {
    "theme",
    "conversation_width",
    "conversation_font_size",
    "model_candidates",
    "clarification_mode",
}
_PROJECT_SETTINGS_FIELDS = {"output_mode", "execution"}

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
    provider_efforts = raw.get("effort_options") or ("low", "medium", "high")
    efforts = ("auto", *(value for value in provider_efforts if value != "auto"))
    return {
        "toolCalling": bool(raw.get("tools", raw.get("tool_calling", True))),
        "structuredOutput": bool(raw.get("structured_output", True)),
        "imageInput": bool(raw.get("image_input", False)),
        "imageGeneration": bool(raw.get("image_generation", False)),
        "contextWindow": raw.get("context_window"),
        "maxInputTokens": raw.get("max_input_tokens"),
        "effortOptions": [
            {
                "id": value,
                "label": {
                    "auto": "자동",
                    "low": "낮음",
                    "medium": "중간",
                    "high": "높음",
                }.get(value, value),
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
    UserSetting | None,
]:
    theme_setting = _setting(db, user.id, "ui.theme")
    theme = theme_setting.value_json if theme_setting else "light"
    conversation_width_setting = _setting(db, user.id, "ui.conversation_width")
    conversation_font_size_setting = _setting(db, user.id, "ui.conversation_font_size")
    conversation_width = (
        conversation_width_setting.value_json if conversation_width_setting else 900
    )
    conversation_font_size = (
        conversation_font_size_setting.value_json if conversation_font_size_setting else 14
    )
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
    else:
        execution, execution_source = initial_execution_selection(
            db,
            organization_id=user.organization_id,
            environment=settings.environment,
        )
    model_candidates_setting = _setting(db, user.id, "models.candidates")
    model_candidates = (
        dict(model_candidates_setting.value_json)
        if model_candidates_setting
        else _default_model_candidates(db)
    )
    clarification_setting = _setting(db, user.id, "agent.clarification_mode")
    clarification_mode = (
        clarification_setting.value_json if clarification_setting else "balanced"
    )
    result: dict[str, Any] = {
        "theme": theme if theme in {"light", "dark"} else "light",
        "conversationWidth": (
            conversation_width
            if isinstance(conversation_width, int) and 600 <= conversation_width <= 1400
            else 900
        ),
        "conversationFontSize": (
            conversation_font_size
            if isinstance(conversation_font_size, int) and 14 <= conversation_font_size <= 24
            else 14
        ),
        "outputMode": output_mode
        if output_mode in {"auto", "chat", "file"}
        else "auto",
        "execution": execution,
        "modelCandidates": model_candidates,
        "clarificationMode": clarification_mode
        if clarification_mode in {"autonomous", "balanced", "confirming"}
        else "balanced",
        "source": {"theme": "user", "execution": execution_source},
        "warnings": [],
    }
    result["revision"] = _settings_revision(
        result,
        user,
        project,
        theme_setting,
        execution_setting,
        model_candidates_setting,
        clarification_setting,
    )
    return (
        result,
        theme_setting,
        execution_setting,
        model_candidates_setting,
        clarification_setting,
    )


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
    user: User,
    project: Project,
    theme: UserSetting | None,
    execution: UserSetting | ProjectSetting | None,
    model_candidates: UserSetting | None,
    clarification: UserSetting | None,
) -> str:
    payload = {
        "value": value,
        "user_settings_revision": user.settings_revision,
        "project_settings_revision": (
            project.settings_revision if project.project_type == "shared" else None
        ),
        "theme_updated": theme.updated_at.isoformat() if theme else None,
        "execution_updated": execution.updated_at.isoformat() if execution else None,
        "model_candidates_updated": (
            model_candidates.updated_at.isoformat() if model_candidates else None
        ),
        "clarification_updated": clarification.updated_at.isoformat()
        if clarification
        else None,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    ).hexdigest()[:24]


def _raise_settings_revision_conflict(db: Session) -> NoReturn:
    db.rollback()
    raise ApiProblem(
        409, "settings_revision_conflict", "설정이 다른 곳에서 변경되었습니다."
    )


def _claim_settings_revision(
    db: Session,
    *,
    user: User,
    project: Project,
    payload: SettingsPatch,
) -> None:
    changed_fields = payload.model_fields_set - {"expected_revision"}
    user_fields = set(_USER_SETTINGS_FIELDS)
    if project.project_type != "shared":
        user_fields.update(_PROJECT_SETTINGS_FIELDS)

    if changed_fields & user_fields:
        expected_user_revision = user.settings_revision
        result = db.execute(
            update(User)
            .where(
                User.id == user.id,
                User.settings_revision == expected_user_revision,
            )
            .values(settings_revision=expected_user_revision + 1)
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", 0) != 1:
            _raise_settings_revision_conflict(db)
        db.expire(user, ["settings_revision"])

    if (
        project.project_type == "shared"
        and changed_fields & _PROJECT_SETTINGS_FIELDS
    ):
        expected_project_revision = project.settings_revision
        result = db.execute(
            update(Project)
            .where(
                Project.id == project.id,
                Project.settings_revision == expected_project_revision,
            )
            .values(settings_revision=expected_project_revision + 1)
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", 0) != 1:
            _raise_settings_revision_conflict(db)
        db.expire(project, ["settings_revision"])


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
    result, _theme, _execution, _model_candidates, _clarification = _resolved_settings(
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
    (
        current,
        theme_setting,
        execution_setting,
        model_candidates_setting,
        clarification_setting,
    ) = (
        _resolved_settings(db, context.user, project, settings)
    )
    if current["revision"] != payload.expected_revision:
        _raise_settings_revision_conflict(db)
    _claim_settings_revision(
        db,
        user=context.user,
        project=project,
        payload=payload,
    )
    if payload.theme is not None:
        if theme_setting is None:
            theme_setting = UserSetting(
                user_id=context.user.id, key="ui.theme", value_json=payload.theme
            )
            db.add(theme_setting)
        else:
            theme_setting.value_json = payload.theme
    for field_name, key in (
        ("conversation_width", "ui.conversation_width"),
        ("conversation_font_size", "ui.conversation_font_size"),
    ):
        value = getattr(payload, field_name)
        if value is None:
            continue
        target = _setting(db, context.user.id, key)
        if target is None:
            db.add(UserSetting(user_id=context.user.id, key=key, value_json=value))
        else:
            target.value_json = value
    if payload.output_mode is not None:
        key = "composer.output_mode"
        output_target: UserSetting | ProjectSetting | None
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
    if payload.clarification_mode is not None:
        if clarification_setting is None:
            clarification_setting = UserSetting(
                user_id=context.user.id,
                key="agent.clarification_mode",
                value_json=payload.clarification_mode,
            )
            db.add(clarification_setting)
        else:
            clarification_setting.value_json = payload.clarification_mode
    db.commit()
    result, _theme, _execution, _model_candidates, _clarification = _resolved_settings(
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
