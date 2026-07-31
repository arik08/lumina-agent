from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from lumina.agent.executor import LocalRunExecutor
from lumina.auth.service import bootstrap_database
from lumina.config import Settings
from lumina.db import SessionLocal, configure_database, create_schema, session_scope
from lumina.models import Conversation, Project, PromptCacheSeed, Run, User, utc_now
from lumina.providers import (
    ProviderMessage,
    ProviderRequest,
    ProviderRequestError,
    ProviderUsage,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'codex-prewarm.db').as_posix()}",
        data_dir=tmp_path,
        files_dir=tmp_path / "files",
        artifacts_dir=tmp_path / "artifacts",
        cookie_secure=False,
    )


def _seed_run(settings: Settings) -> tuple[str, str]:
    configure_database(settings.database_url)
    create_schema()
    bootstrap_database(settings=settings)
    with session_scope() as db:
        user = db.scalar(select(User).where(User.login_id == "admin@posco.com"))
        assert user is not None
        project = db.scalar(select(Project).where(Project.owner_user_id == user.id))
        assert project is not None
        conversation = Conversation(
            organization_id=user.organization_id,
            project_id=project.id,
            owner_user_id=user.id,
            title="Cache seed",
        )
        db.add(conversation)
        db.flush()
        run = Run(
            organization_id=user.organization_id,
            project_id=project.id,
            conversation_id=conversation.id,
            user_id=user.id,
            status="preparing",
            provider_id="codex",
            model_key="gpt-5.5",
            runtime_model_id="gpt-5.5",
            model_display_name="GPT-5.5",
        )
        db.add(run)
        db.flush()
        return run.id, user.id


def _request(cache_key: str, *, tool_name: str = "lookup") -> ProviderRequest:
    return ProviderRequest(
        model="gpt-5.5",
        messages=(
            ProviderMessage(role="system", content="stable system prompt"),
            ProviderMessage(role="system", content="dynamic turn contract"),
            ProviderMessage(role="user", content="hello"),
        ),
        tools=(
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Lookup",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ),
        effort="medium",
        metadata={"prompt_cache_key": cache_key},
    )


def test_codex_cache_seed_persists_only_the_static_prefix(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    run_id, user_id = _seed_run(settings)
    executor = LocalRunExecutor(settings)
    request = _request("lumina:user:v3:first")

    executor._remember_codex_cache_seed(
        run_id,
        request,
        static_digest="a" * 64,
    )

    with SessionLocal() as db:
        seed = db.scalar(select(PromptCacheSeed))
        assert seed is not None
        assert seed.user_id == user_id
        assert seed.prompt_cache_key == "lumina:user:v3:first"
        assert seed.static_digest == "a" * 64
        assert seed.system_content == "stable system prompt"
        assert seed.tools_json[0]["function"]["name"] == "lookup"
        assert seed.effort == "medium"


def test_codex_cache_seed_history_is_bounded_per_user_model(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    run_id, _user_id = _seed_run(settings)
    executor = LocalRunExecutor(settings)

    for index in range(6):
        executor._remember_codex_cache_seed(
            run_id,
            _request(f"lumina:user:v3:{index}"),
            static_digest=f"{index:064d}",
        )

    with SessionLocal() as db:
        keys = set(db.scalars(select(PromptCacheSeed.prompt_cache_key)))
    assert len(keys) == 4
    assert keys == {f"lumina:user:v3:{index}" for index in range(2, 6)}


@pytest.mark.asyncio
async def test_codex_cache_seed_prewarms_latest_user_model_scope_and_records_usage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    run_id, _user_id = _seed_run(settings)
    executor = LocalRunExecutor(settings)
    executor._remember_codex_cache_seed(
        run_id,
        _request("lumina:user:v3:old", tool_name="old_lookup"),
        static_digest="a" * 64,
    )
    executor._remember_codex_cache_seed(
        run_id,
        _request("lumina:user:v3:new", tool_name="new_lookup"),
        static_digest="b" * 64,
    )
    with session_scope() as db:
        old_seed = db.scalar(
            select(PromptCacheSeed).where(
                PromptCacheSeed.prompt_cache_key == "lumina:user:v3:old"
            )
        )
        new_seed = db.scalar(
            select(PromptCacheSeed).where(
                PromptCacheSeed.prompt_cache_key == "lumina:user:v3:new"
            )
        )
        assert old_seed is not None
        assert new_seed is not None
        old_seed.last_used_at = old_seed.last_used_at.replace(year=2025)
        new_seed_id = new_seed.id

    warmed: list[ProviderRequest] = []

    async def warmup() -> None:
        return None

    async def prewarm(request: ProviderRequest) -> ProviderUsage:
        warmed.append(request)
        return ProviderUsage(
            input_tokens=120,
            cached_input_tokens=96,
            uncached_input_tokens=24,
            output_tokens=1,
        )

    monkeypatch.setattr(executor.codex_provider, "warmup", warmup)
    monkeypatch.setattr(executor.codex_provider, "prewarm", prewarm)

    await executor._warm_codex_provider()

    assert len(warmed) == 1
    assert warmed[0].metadata["prompt_cache_key"] == "lumina:user:v3:new"
    assert warmed[0].messages[0].content == "stable system prompt"
    assert warmed[0].messages[1].role == "user"
    assert warmed[0].tools[0]["function"]["name"] == "new_lookup"
    assert warmed[0].effort == "low"
    with SessionLocal() as db:
        seed = db.get(PromptCacheSeed, new_seed_id)
        assert seed is not None
        assert seed.last_warmed_at is not None
        assert seed.last_warm_input_tokens == 120
        assert seed.last_warm_cached_tokens == 96


@pytest.mark.asyncio
async def test_codex_cache_prewarm_failure_does_not_block_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    run_id, _user_id = _seed_run(settings)
    executor = LocalRunExecutor(settings)
    executor._remember_codex_cache_seed(
        run_id,
        _request("lumina:user:v3:failure"),
        static_digest="f" * 64,
    )

    async def warmup() -> None:
        return None

    async def prewarm(_request: ProviderRequest) -> ProviderUsage:
        raise ProviderRequestError(
            "temporary prewarm failure",
            retryable=True,
            stage="network",
        )

    monkeypatch.setattr(executor.codex_provider, "warmup", warmup)
    monkeypatch.setattr(executor.codex_provider, "prewarm", prewarm)

    await executor._warm_codex_provider()

    with SessionLocal() as db:
        seed = db.scalar(select(PromptCacheSeed))
        assert seed is not None
        assert seed.last_warmed_at is None


@pytest.mark.asyncio
async def test_codex_cache_prewarm_skips_recently_warmed_and_stale_seeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    run_id, _user_id = _seed_run(settings)
    executor = LocalRunExecutor(settings)
    executor._remember_codex_cache_seed(
        run_id,
        _request("lumina:user:v3:recent"),
        static_digest="c" * 64,
    )
    executor._remember_codex_cache_seed(
        run_id,
        _request("lumina:user:v3:stale"),
        static_digest="d" * 64,
    )
    with session_scope() as db:
        recent = db.scalar(
            select(PromptCacheSeed).where(
                PromptCacheSeed.prompt_cache_key == "lumina:user:v3:recent"
            )
        )
        stale = db.scalar(
            select(PromptCacheSeed).where(
                PromptCacheSeed.prompt_cache_key == "lumina:user:v3:stale"
            )
        )
        assert recent is not None and stale is not None
        recent.last_warmed_at = utc_now()
        stale.last_used_at = stale.last_used_at.replace(year=2025)

    warmed: list[ProviderRequest] = []

    async def warmup() -> None:
        return None

    async def prewarm(request: ProviderRequest) -> ProviderUsage:
        warmed.append(request)
        return ProviderUsage(input_tokens=1, output_tokens=1)

    monkeypatch.setattr(executor.codex_provider, "warmup", warmup)
    monkeypatch.setattr(executor.codex_provider, "prewarm", prewarm)

    await executor._warm_codex_provider()

    assert warmed == []
