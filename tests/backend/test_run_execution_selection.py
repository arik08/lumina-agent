from __future__ import annotations

import pytest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from lumina.api.errors import ApiProblem
from lumina.api.schemas import (
    ExecutionSelection,
    RunCreate,
    RunMessageInput,
)
from lumina.auth import bootstrap_database
from lumina.config import Settings
from lumina.db import Base
from lumina.models import (
    Organization,
    Project,
    ProjectSetting,
    ProviderModel,
    User,
    UserSetting,
)
from lumina.runs.service import resolve_execution


def _settings(tmp_path, environment: str) -> Settings:
    return Settings(environment=environment, data_dir=tmp_path / environment)


def _payload(execution: ExecutionSelection | None = None) -> RunCreate:
    return RunCreate(
        message=RunMessageInput(text="실행 설정을 확인해 주세요."),
        execution=execution,
    )


def test_execution_defaults_use_server_scope_and_production_rejects_mock(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'selection.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db_session:
        _assert_execution_selection(db_session, tmp_path)
    engine.dispose()


def test_organization_initial_execution_only_applies_before_user_selection(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'initial-selection.db').as_posix()}"
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    production = _settings(tmp_path, "production")
    with session_factory() as db_session:
        bootstrap_database(db_session, settings=production)
        user = db_session.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert user is not None
        project = db_session.scalar(
            select(Project).where(
                Project.owner_user_id == user.id,
                Project.is_default.is_(True),
            )
        )
        organization = db_session.get(Organization, user.organization_id)
        assert project is not None
        assert organization is not None
        organization.initial_execution_settings_json = {
            "providerId": "pgpt",
            "modelKey": "gpt-5.4-mini",
            "effortId": "high",
        }
        db_session.flush()

        initial = resolve_execution(
            db_session,
            _payload(),
            user=user,
            project=project,
            settings=production,
        )
        assert (initial["provider_id"], initial["model_key"], initial["effort"]) == (
            "pgpt",
            "gpt-5.4-mini",
            "high",
        )

        db_session.add(
            UserSetting(
                user_id=user.id,
                key="execution.default",
                value_json={
                    "providerId": "pgpt",
                    "modelKey": "gpt-5.4",
                    "effortId": "low",
                },
            )
        )
        organization.initial_execution_settings_json = {
            "providerId": "codex",
            "modelKey": "gpt-5.5",
            "effortId": "medium",
        }
        db_session.flush()

        returning = resolve_execution(
            db_session,
            _payload(),
            user=user,
            project=project,
            settings=production,
        )
        assert (
            returning["provider_id"],
            returning["model_key"],
            returning["effort"],
        ) == ("pgpt", "gpt-5.4", "low")
    engine.dispose()


def test_maximum_context_mode_is_pinned_to_the_run_snapshot(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'context-mode.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    production = _settings(tmp_path, "production")
    with session_factory() as db_session:
        bootstrap_database(db_session, settings=production)
        user = db_session.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert user is not None
        project = db_session.scalar(
            select(Project).where(
                Project.owner_user_id == user.id,
                Project.is_default.is_(True),
            )
        )
        model = db_session.scalar(
            select(ProviderModel).where(
                ProviderModel.provider_id == "pgpt",
                ProviderModel.model_key == "gpt-5.4",
            )
        )
        assert project is not None
        assert model is not None
        model.capabilities_json = {
            **model.capabilities_json,
            "context_capacity_mode": "maximum",
            "context_window": 1_050_000,
            "max_input_tokens": 911_900,
            "context_compaction_threshold": 0.75,
        }
        db_session.flush()

        resolved = resolve_execution(
            db_session,
            _payload(ExecutionSelection(
                provider_id="pgpt",
                model_key="gpt-5.4",
                effort_id="high",
            )),
            user=user,
            project=project,
            settings=production,
        )

        assert resolved["capabilities"]["context_capacity_mode"] == "maximum"
        assert resolved["capabilities"]["context_window"] == 1_050_000
        assert resolved["capabilities"]["max_input_tokens"] == 911_900
        assert resolved["capabilities"]["context_compaction_threshold"] == 0.75
    engine.dispose()


def _assert_execution_selection(db_session: Session, tmp_path: Path) -> None:
    production = _settings(tmp_path, "production")
    bootstrap_database(db_session, settings=production)
    user = db_session.scalar(select(User).where(User.login_id == "admin@posco.com"))
    assert user is not None
    project = db_session.scalar(
        select(Project).where(
            Project.owner_user_id == user.id,
            Project.is_default.is_(True),
        )
    )
    assert project is not None
    db_session.add_all(
        [
            UserSetting(
                user_id=user.id,
                key="execution.default",
                value_json={
                    "providerId": "openai",
                    "modelKey": "gpt-5.6-sol",
                    "effortId": "high",
                },
            ),
            ProjectSetting(
                project_id=project.id,
                key="execution.default",
                value_json={
                    "providerId": "anthropic",
                    "modelKey": "claude-sonnet-5",
                    "effortId": "medium",
                },
                updated_by_user_id=user.id,
            ),
        ]
    )
    db_session.flush()

    personal = resolve_execution(
        db_session,
        _payload(),
        user=user,
        project=project,
        settings=production,
    )
    assert (personal["provider_id"], personal["model_key"], personal["effort"]) == (
        "openai",
        "gpt-5.6-sol",
        "high",
    )

    project.project_type = "shared"
    shared = resolve_execution(
        db_session,
        _payload(),
        user=user,
        project=project,
        settings=production,
    )
    assert (shared["provider_id"], shared["model_key"]) == (
        "anthropic",
        "claude-sonnet-5",
    )

    user_setting = db_session.scalar(
        select(UserSetting).where(
            UserSetting.user_id == user.id,
            UserSetting.key == "execution.default",
        )
    )
    assert user_setting is not None
    project.project_type = "personal"
    user_setting.value_json = {
        "providerId": "mock",
        "modelKey": "mock-agent",
        "effortId": "medium",
    }
    db_session.flush()
    fallback = resolve_execution(
        db_session,
        _payload(),
        user=user,
        project=project,
        settings=production,
    )
    assert (fallback["provider_id"], fallback["model_key"]) == ("pgpt", "gpt-5.4")
    assert fallback["fallback_messages"]
    assert fallback["capabilities"]["context_window"] == 272_000
    assert fallback["capabilities"]["context_capacity_mode"] == "standard"
    assert (
        fallback["capabilities"]["standard_context_compaction_reserve_tokens"]
        == 20_000
    )
    assert fallback["capabilities"]["max_output_tokens"] == 128_000
    assert fallback["capabilities"]["configured_max_output_tokens"] == 42_000

    with pytest.raises(ApiProblem) as explicit_mock:
        resolve_execution(
            db_session,
            _payload(ExecutionSelection()),
            user=user,
            project=project,
            settings=production,
        )
    assert explicit_mock.value.code == "mock_provider_forbidden"

    development = resolve_execution(
        db_session,
        _payload(ExecutionSelection()),
        settings=_settings(tmp_path, "test"),
    )
    assert development["provider_id"] == "mock"
