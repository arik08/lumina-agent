from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import (
    AuditEvent,
    AuthSession,
    Organization,
    Project,
    ProjectMembership,
    ProviderModel,
    User,
)
from ..providers.catalog import initial_model_catalog
from .security import (
    generate_secret_token,
    hash_password,
    hash_token,
    next_seoul_midnight,
    normalize_login_parts,
    normalize_login_id,
    password_needs_rehash,
    token_matches,
    verify_password,
)


BOOTSTRAP_ADMIN_LOGIN_ID = "admin@posco.com"
BOOTSTRAP_ADMIN_PASSWORD = "1"
DEFAULT_ORGANIZATION_SLUG = "posco"
DEFAULT_PROJECT_NAME = "기본 프로젝트"
CATALOG_REVISION = "2026-07-11.initial"


class AuthenticationError(Exception):
    def __init__(self, code: str = "invalid_credentials") -> None:
        super().__init__(code)
        self.code = code


class AccountUnavailableError(AuthenticationError):
    pass


@dataclass(frozen=True, slots=True)
class IssuedAuthSession:
    auth_session: AuthSession
    session_token: str
    csrf_token: str


@dataclass(frozen=True, slots=True)
class ResolvedAuthSession:
    auth_session: AuthSession
    user: User


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    organization_id: str
    admin_user_id: str
    admin_created: bool
    provider_models_created: int


@dataclass(frozen=True, slots=True)
class ModelSeed:
    provider_id: str
    display_name: str
    runtime_model_id: str
    is_default: bool
    sort_order: int
    source: str

    @property
    def model_key(self) -> str:
        return self.runtime_model_id


MODEL_CATALOG_SEEDS: tuple[ModelSeed, ...] = (
    ModelSeed("pgpt", "GPT-5.4", "gpt-5.4", True, 10, "product_contract:user"),
    ModelSeed(
        "pgpt", "GPT-5.4-mini", "gpt-5.4-mini", False, 20, "product_contract:user"
    ),
    ModelSeed("codex", "GPT-5.5", "gpt-5.5", True, 10, "product_contract:user"),
    ModelSeed("codex", "GPT-5.4", "gpt-5.4", False, 20, "product_contract:user"),
    ModelSeed(
        "google", "Gemini-3.1-Pro", "gemini-3.1-pro", True, 10, "product_contract:user"
    ),
    ModelSeed(
        "google",
        "Gemini-3.5-flash",
        "gemini-3.5-flash",
        False,
        20,
        "product_contract:user",
    ),
    ModelSeed(
        "openai", "GPT-5.6-Sol", "gpt-5.6-sol", True, 10, "official_docs:2026-07-11"
    ),
    ModelSeed(
        "openai",
        "GPT-5.6-Terra",
        "gpt-5.6-terra",
        False,
        20,
        "official_docs:2026-07-11",
    ),
    ModelSeed(
        "openai", "GPT-5.6-Luna", "gpt-5.6-luna", False, 30, "official_docs:2026-07-11"
    ),
    ModelSeed(
        "anthropic",
        "Claude Opus 4.8",
        "claude-opus-4-8",
        False,
        10,
        "official_docs:2026-07-11",
    ),
    ModelSeed(
        "anthropic",
        "Claude Sonnet 5",
        "claude-sonnet-5",
        True,
        20,
        "official_docs:2026-07-11",
    ),
    ModelSeed(
        "anthropic",
        "Claude Haiku 4.5",
        "claude-haiku-4-5",
        False,
        30,
        "official_docs:2026-07-11",
    ),
)

_CATALOG_SEEDS_BY_KEY = {
    (item.provider_id, item.model_key): item for item in initial_model_catalog()
}


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


def _audit(
    session: Session,
    *,
    action: str,
    target_type: str,
    result: str,
    organization_id: str | None = None,
    actor_user_id: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=result,
            metadata_json=metadata or {},
        )
    )


def ensure_default_project(session: Session, user: User) -> Project:
    project = session.scalar(
        select(Project).where(
            Project.owner_user_id == user.id, Project.is_default.is_(True)
        )
    )
    if project is None:
        project = Project(
            organization_id=user.organization_id,
            owner_user_id=user.id,
            name=DEFAULT_PROJECT_NAME,
            project_type="personal",
            visibility="private",
            is_default=True,
        )
        session.add(project)
        session.flush()

    membership = session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.user_id == user.id,
        )
    )
    if membership is None:
        session.add(
            ProjectMembership(
                project_id=project.id,
                user_id=user.id,
                role="owner",
                status="active",
                created_by_user_id=user.id,
            )
        )
    return project


def create_user(
    session: Session,
    *,
    login_name: str,
    login_domain: str = "posco.com",
    password: str,
    organization_id: str,
    display_name: str | None = None,
    affiliation: str | None = None,
    role: str = "user",
    status: str = "active",
    must_change_password: bool = False,
    created_by_user_id: str | None = None,
) -> User:
    normalized_name, normalized_domain, login_id = normalize_login_parts(
        login_name, login_domain
    )
    if session.scalar(select(User.id).where(User.login_id == login_id)) is not None:
        raise ValueError("login_id already exists")

    user = User(
        organization_id=organization_id,
        login_name=normalized_name,
        login_domain=normalized_domain,
        login_id=login_id,
        display_name=display_name,
        affiliation=affiliation,
        password_hash=hash_password(password),
        role=role,
        status=status,
        must_change_password=must_change_password,
        created_by_user_id=created_by_user_id,
    )
    session.add(user)
    session.flush()
    ensure_default_project(session, user)
    _audit(
        session,
        action="user_created",
        target_type="user",
        target_id=user.id,
        organization_id=user.organization_id,
        actor_user_id=created_by_user_id,
        result="success",
    )
    session.flush()
    return user


def seed_provider_models(session: Session) -> int:
    existing_models = {
        (item.provider_id, item.model_key): item
        for item in session.scalars(select(ProviderModel)).all()
    }
    providers_with_default = {
        item.provider_id for item in existing_models.values() if item.is_default
    }
    created = 0
    verified_at = datetime(2026, 7, 12, tzinfo=UTC)

    for seed in MODEL_CATALOG_SEEDS:
        key = (seed.provider_id, seed.model_key)
        catalog_seed = _CATALOG_SEEDS_BY_KEY[key]
        capabilities = {
            **asdict(catalog_seed.capabilities),
            "verification_status": "verified",
        }
        existing = existing_models.get(key)
        if existing is not None:
            existing_capabilities = existing.capabilities_json
            if existing.source == seed.source:
                existing.display_name = seed.display_name
            if (
                existing.source == seed.source
                and existing_capabilities.get("verification_status")
                == "adapter_merge_required"
            ):
                existing.capabilities_json = {
                    **existing_capabilities,
                    **capabilities,
                }
                existing.catalog_revision = catalog_seed.catalog_revision
                existing.verified_at = verified_at
            continue
        is_default = seed.is_default and seed.provider_id not in providers_with_default
        model = ProviderModel(
            provider_id=seed.provider_id,
            model_key=seed.model_key,
            display_name=seed.display_name,
            runtime_model_id=seed.runtime_model_id,
            enabled=True,
            is_default=is_default,
            sort_order=seed.sort_order,
            capabilities_json=capabilities,
            source=seed.source,
            catalog_revision=catalog_seed.catalog_revision,
            verified_at=verified_at,
        )
        session.add(model)
        existing_models[key] = model
        if is_default:
            providers_with_default.add(seed.provider_id)
        created += 1
    session.flush()
    return created


def _bootstrap(session: Session, settings: Settings) -> BootstrapResult:
    organization = session.scalar(
        select(Organization).where(Organization.slug == DEFAULT_ORGANIZATION_SLUG)
    )
    if organization is None:
        permission_mode = (
            "auto" if settings.environment == "development" else "admin_review"
        )
        organization = Organization(
            slug=DEFAULT_ORGANIZATION_SLUG,
            name="POSCO",
            marketplace_permission_mode=permission_mode,
        )
        session.add(organization)
        session.flush()
    elif organization.marketplace_permission_mode not in {"auto", "admin_review"}:
        organization.marketplace_permission_mode = "admin_review"

    _, _, admin_login_id = normalize_login_id(BOOTSTRAP_ADMIN_LOGIN_ID)
    admin = session.scalar(select(User).where(User.login_id == admin_login_id))
    admin_created = admin is None
    if admin is None:
        admin = create_user(
            session,
            login_name="admin",
            login_domain="posco.com",
            password=BOOTSTRAP_ADMIN_PASSWORD,
            organization_id=organization.id,
            display_name="Administrator",
            role="admin",
            status="active",
            must_change_password=False,
        )

    for user in session.scalars(select(User)).all():
        ensure_default_project(session, user)

    provider_models_created = seed_provider_models(session)
    if settings.environment != "test":
        from ..extensions.repository_catalog import sync_repository_catalog

        sync_repository_catalog(session, admin=admin)
    session.flush()
    return BootstrapResult(
        organization_id=organization.id,
        admin_user_id=admin.id,
        admin_created=admin_created,
        provider_models_created=provider_models_created,
    )


def bootstrap_database(
    session: Session | None = None, *, settings: Settings | None = None
) -> BootstrapResult:
    config = settings or get_settings()
    if session is not None:
        return _bootstrap(session, config)

    from ..db import create_schema, session_scope

    create_schema()
    with session_scope() as managed_session:
        return _bootstrap(managed_session, config)


def authenticate_user(
    session: Session,
    *,
    login_name: str,
    login_domain: str,
    password: str,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> User:
    config = settings or get_settings()
    timestamp = _utc_now(now)
    try:
        _, _, login_id = normalize_login_parts(login_name, login_domain)
    except ValueError as exc:
        raise AuthenticationError() from exc

    user = session.scalar(select(User).where(User.login_id == login_id))
    if user is None:
        # Perform one Argon2 verification to reduce account-enumeration timing differences.
        verify_password(password, _DUMMY_PASSWORD_HASH)
        _audit(
            session,
            action="login_failed",
            target_type="user",
            result="denied",
            metadata={"reason": "invalid_credentials"},
        )
        session.flush()
        raise AuthenticationError()

    if user.status != "active":
        _audit(
            session,
            action="login_failed",
            target_type="user",
            target_id=user.id,
            organization_id=user.organization_id,
            result="denied",
            metadata={"reason": "account_unavailable"},
        )
        session.flush()
        raise AccountUnavailableError("account_unavailable")
    if user.locked_until is not None and user.locked_until > timestamp:
        raise AccountUnavailableError("temporarily_locked")

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= config.login_max_failed_attempts:
            user.locked_until = timestamp + timedelta(seconds=config.login_lock_seconds)
        _audit(
            session,
            action="login_failed",
            target_type="user",
            target_id=user.id,
            organization_id=user.organization_id,
            result="denied",
            metadata={"reason": "invalid_credentials"},
        )
        session.flush()
        raise AuthenticationError()

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = timestamp
    _audit(
        session,
        action="login_succeeded",
        target_type="user",
        target_id=user.id,
        organization_id=user.organization_id,
        actor_user_id=user.id,
        result="success",
    )
    session.flush()
    return user


def issue_server_session(
    session: Session, user: User, *, now: datetime | None = None
) -> IssuedAuthSession:
    timestamp = _utc_now(now)
    session_token = generate_secret_token()
    csrf_token = generate_secret_token()
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(session_token),
        csrf_token_hash=hash_token(csrf_token),
        created_at=timestamp,
        last_seen_at=timestamp,
        expires_at=next_seoul_midnight(timestamp),
    )
    session.add(auth_session)
    session.flush()
    return IssuedAuthSession(auth_session, session_token, csrf_token)


def resolve_server_session(
    session: Session, session_token: str, *, now: datetime | None = None
) -> ResolvedAuthSession | None:
    timestamp = _utc_now(now)
    auth_session = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_token(session_token))
    )
    if auth_session is None or auth_session.revoked_at is not None:
        return None
    if auth_session.expires_at <= timestamp:
        auth_session.revoked_at = timestamp
        session.flush()
        return None

    user = session.get(User, auth_session.user_id)
    if user is None or user.status != "active":
        auth_session.revoked_at = timestamp
        session.flush()
        return None
    return ResolvedAuthSession(auth_session, user)


def verify_csrf_token(auth_session: AuthSession, csrf_token: str) -> bool:
    return token_matches(csrf_token, auth_session.csrf_token_hash)


def revoke_server_session(
    session: Session, session_token: str, *, now: datetime | None = None
) -> bool:
    auth_session = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_token(session_token))
    )
    if auth_session is None or auth_session.revoked_at is not None:
        return False
    auth_session.revoked_at = _utc_now(now)
    session.flush()
    return True


def revoke_user_sessions(
    session: Session, user_id: str, *, now: datetime | None = None
) -> int:
    timestamp = _utc_now(now)
    sessions = session.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
        )
    ).all()
    for auth_session in sessions:
        auth_session.revoked_at = timestamp
    session.flush()
    return len(sessions)


_DUMMY_PASSWORD_HASH = hash_password("lumina-dummy-password")
