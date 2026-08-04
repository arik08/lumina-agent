from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from lumina.auth import (
    AuthenticationError,
    authenticate_user,
    bootstrap_database,
    create_user,
    hash_password,
    issue_server_session,
    next_seoul_midnight,
    resolve_server_session,
    revoke_server_session,
    verify_csrf_token,
    verify_password,
)
from lumina.config import Settings
from lumina.db import Base
from lumina.models import (
    AuthSession,
    Organization,
    Project,
    ProjectMembership,
    ProviderModel,
    User,
)


@pytest.fixture()
def db_session(tmp_path) -> Session:
    database_path = tmp_path / "lumina-test.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with test_session_factory() as session:
        yield session
        session.rollback()
    engine.dispose()


@pytest.fixture()
def test_settings(tmp_path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'unused.db').as_posix()}",
        data_dir=tmp_path / "data",
        login_max_failed_attempts=2,
        login_lock_seconds=60,
    )


def test_bootstrap_is_idempotent_and_seeds_contract_data(
    db_session: Session, test_settings: Settings
) -> None:
    first = bootstrap_database(db_session, settings=test_settings)
    db_session.commit()
    second = bootstrap_database(db_session, settings=test_settings)
    db_session.commit()

    assert first.admin_created is True
    assert first.provider_models_created == 19
    assert second.admin_created is False
    assert second.provider_models_created == 0

    admin = db_session.scalar(select(User).where(User.login_id == "admin@posco.com"))
    assert admin is not None
    assert admin.role == "admin"
    assert admin.status == "active"
    assert admin.must_change_password is False
    assert admin.password_hash.startswith("$argon2id$")
    assert verify_password("1111", admin.password_hash)
    assert not verify_password("1", admin.password_hash)

    default_projects = db_session.scalars(
        select(Project).where(
            Project.owner_user_id == admin.id, Project.is_default.is_(True)
        )
    ).all()
    assert len(default_projects) == 1
    assert default_projects[0].concept == ""
    membership = db_session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == default_projects[0].id,
            ProjectMembership.user_id == admin.id,
        )
    )
    assert membership is not None
    assert membership.role == "owner"

    organization = db_session.get(Organization, admin.organization_id)
    assert organization is not None
    assert organization.marketplace_permission_mode == "admin_review"
    assert db_session.scalar(select(func.count()).select_from(ProviderModel)) == 19


def test_bootstrap_refreshes_contract_display_names_without_overwriting_admin_names(
    db_session: Session, test_settings: Settings
) -> None:
    bootstrap_database(db_session, settings=test_settings)
    codex_model = db_session.scalar(
        select(ProviderModel).where(
            ProviderModel.provider_id == "codex",
            ProviderModel.model_key == "gpt-5.4",
        )
    )
    assert codex_model is not None

    codex_model.display_name = "Codex 5.4"
    db_session.commit()
    bootstrap_database(db_session, settings=test_settings)
    assert codex_model.display_name == "GPT-5.4"

    codex_model.display_name = "Team Codex"
    codex_model.source = "admin_manual"
    db_session.commit()
    bootstrap_database(db_session, settings=test_settings)
    assert codex_model.display_name == "Team Codex"

    defaults = {
        model.provider_id: model.runtime_model_id
        for model in db_session.scalars(
            select(ProviderModel).where(ProviderModel.is_default.is_(True))
        )
    }
    assert defaults == {
        "anthropic": "claude-sonnet-5",
        "codex": "gpt-5.5",
        "google": "gemini-3.1-pro",
        "openai": "gpt-5.6-sol",
        "pgpt": "gpt-5.4",
    }


def test_bootstrap_never_overwrites_existing_admin_password_or_model_mapping(
    db_session: Session, test_settings: Settings
) -> None:
    bootstrap_database(db_session, settings=test_settings)
    db_session.commit()
    admin = db_session.scalar(select(User).where(User.login_id == "admin@posco.com"))
    model = db_session.scalar(
        select(ProviderModel).where(
            ProviderModel.provider_id == "pgpt", ProviderModel.model_key == "gpt-5.4"
        )
    )
    assert admin is not None and model is not None

    changed_hash = hash_password("changed-by-admin")
    admin.password_hash = changed_hash
    model.runtime_model_id = "company-deployment-gpt54"
    db_session.commit()

    bootstrap_database(db_session, settings=test_settings)
    db_session.commit()
    db_session.refresh(admin)
    db_session.refresh(model)
    assert admin.password_hash == changed_hash
    assert model.runtime_model_id == "company-deployment-gpt54"


def test_bootstrap_upgrades_legacy_admin_password_and_revokes_sessions(
    db_session: Session, test_settings: Settings
) -> None:
    bootstrap_database(db_session, settings=test_settings)
    admin = db_session.scalar(select(User).where(User.login_id == "admin@posco.com"))
    assert admin is not None
    admin.password_hash = hash_password("1")
    issued = issue_server_session(db_session, admin)
    db_session.commit()

    bootstrap_database(db_session, settings=test_settings)
    db_session.commit()
    db_session.refresh(admin)

    assert verify_password("1111", admin.password_hash)
    assert not verify_password("1", admin.password_hash)
    assert resolve_server_session(db_session, issued.session_token) is None


def test_user_creation_normalizes_login_and_creates_one_default_project(
    db_session: Session, test_settings: Settings
) -> None:
    result = bootstrap_database(db_session, settings=test_settings)
    user = create_user(
        db_session,
        login_name="  Hong.GilDong ",
        login_domain=" POSCO.COM. ",
        password="temporary-password",
        organization_id=result.organization_id,
    )
    db_session.commit()

    assert user.login_id == "hong.gildong@posco.com"
    projects = db_session.scalars(
        select(Project).where(
            Project.owner_user_id == user.id, Project.is_default.is_(True)
        )
    ).all()
    assert len(projects) == 1


def test_failed_login_is_counted_and_success_resets_counter(
    db_session: Session, test_settings: Settings
) -> None:
    bootstrap_database(db_session, settings=test_settings)
    db_session.commit()

    with pytest.raises(AuthenticationError):
        authenticate_user(
            db_session,
            login_name="admin",
            login_domain="posco.com",
            password="wrong",
            settings=test_settings,
        )
    db_session.commit()
    admin = db_session.scalar(select(User).where(User.login_id == "admin@posco.com"))
    assert admin is not None
    assert admin.failed_login_count == 1

    authenticated = authenticate_user(
        db_session,
        login_name="ADMIN",
        login_domain="POSCO.COM",
        password="1111",
        settings=test_settings,
    )
    db_session.commit()
    assert authenticated.id == admin.id
    assert authenticated.failed_login_count == 0
    assert authenticated.last_login_at is not None
    assert authenticated.last_login_at.tzinfo is not None


def test_server_session_expires_at_next_seoul_midnight_and_supports_csrf(
    db_session: Session, test_settings: Settings
) -> None:
    bootstrap_database(db_session, settings=test_settings)
    admin = db_session.scalar(select(User).where(User.login_id == "admin@posco.com"))
    assert admin is not None
    now = datetime(2026, 7, 11, 14, 30, tzinfo=UTC)  # 23:30 in Seoul

    issued = issue_server_session(db_session, admin, now=now)
    db_session.commit()
    assert issued.auth_session.expires_at == datetime(2026, 7, 11, 15, 0, tzinfo=UTC)
    assert issued.auth_session.token_hash != issued.session_token
    assert verify_csrf_token(issued.auth_session, issued.csrf_token)
    assert not verify_csrf_token(issued.auth_session, "wrong-csrf-token")

    resolved = resolve_server_session(
        db_session,
        issued.session_token,
        now=datetime(2026, 7, 11, 14, 59, 59, tzinfo=UTC),
    )
    assert resolved is not None
    assert resolved.user.id == admin.id

    assert (
        resolve_server_session(
            db_session,
            issued.session_token,
            now=datetime(2026, 7, 11, 15, 0, tzinfo=UTC),
        )
        is None
    )
    db_session.commit()
    stored = db_session.get(AuthSession, issued.auth_session.id)
    assert stored is not None and stored.revoked_at is not None


def test_logout_revokes_session_idempotently(
    db_session: Session, test_settings: Settings
) -> None:
    bootstrap_database(db_session, settings=test_settings)
    admin = db_session.scalar(select(User).where(User.login_id == "admin@posco.com"))
    assert admin is not None
    issued = issue_server_session(db_session, admin)
    db_session.commit()

    assert revoke_server_session(db_session, issued.session_token) is True
    assert revoke_server_session(db_session, issued.session_token) is False
    db_session.commit()
    assert resolve_server_session(db_session, issued.session_token) is None


def test_next_seoul_midnight_requires_aware_time() -> None:
    with pytest.raises(ValueError):
        next_seoul_midnight(datetime(2026, 7, 11, 12, 0))


def test_production_forces_secure_auth_cookie(tmp_path) -> None:
    settings = Settings(
        environment="production",
        database_url=f"sqlite:///{(tmp_path / 'unused.db').as_posix()}",
        data_dir=tmp_path,
        cookie_secure=False,
    )
    assert settings.cookie_secure is True
