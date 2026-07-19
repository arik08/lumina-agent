from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope
from sqlalchemy import text

from .agent.executor import local_run_executor
from .api.errors import install_error_handlers
from .api.routes import (
    admin,
    admin_providers,
    artifacts,
    attachments,
    auth,
    composer,
    conversations,
    deep_analysis,
    extensions,
    finance,
    help,
    instructions,
    knowledge,
    mcp,
    memories,
    messages,
    notifications,
    project_files,
    project_memberships,
    project_memories,
    projects,
    providers,
    runs,
    schedules,
    sharing,
)
from .auth import bootstrap_database
from .config import REPOSITORY_ROOT, Settings, get_settings
from .db import SessionLocal, configure_database, create_schema, session_scope
from .http_client import TrustManager, TrustProfile
from .extensions.repository_catalog import watch_repository_catalog
from .observability import request_log_path, structured_event
from .schedules.service import local_scheduler


logger = logging.getLogger(__name__)


class StartupTracker:
    """Keep a secret-free, process-local record of Backend startup phases."""

    def __init__(self) -> None:
        self.started_at = datetime.now(UTC)
        self._started_clock = perf_counter()
        self._phase_started_clock = self._started_clock
        self._finished_clock: float | None = None
        self.status = "starting"
        self.phase = "created"
        self.error_code: str | None = None
        self.trust: dict[str, bool | str] | None = None
        self.completed_phases: list[dict[str, float | str]] = []

    def enter(self, phase: str) -> None:
        now = perf_counter()
        self._complete_current_phase(now)
        self.phase = phase
        self._phase_started_clock = now

    def ready(self) -> None:
        now = perf_counter()
        self._complete_current_phase(now)
        self.phase = "ready"
        self.status = "ready"
        self._phase_started_clock = now
        self._finished_clock = now

    def fail(self, error_code: str) -> None:
        now = perf_counter()
        self._complete_current_phase(now)
        self.phase = "failed"
        self.status = "failed"
        self.error_code = error_code
        self._phase_started_clock = now
        self._finished_clock = now

    def record_trust(self, profile: TrustProfile) -> None:
        self.trust = {
            "source": profile.source,
            "companyCaConfigured": profile.company_ca_path is not None,
            "bundleConfigured": profile.bundle_path is not None,
            "tlsCompatMode": profile.tls_compat_mode,
        }

    def snapshot(self, *, executor_started: bool) -> dict[str, Any]:
        now = self._finished_clock or perf_counter()
        return {
            "status": self.status,
            "phase": self.phase,
            "startedAt": self.started_at.isoformat(),
            "elapsedMs": round((now - self._started_clock) * 1000, 3),
            "errorCode": self.error_code,
            "executor": "ready" if executor_started else "stopped",
            "trust": dict(self.trust) if self.trust is not None else None,
            "completedPhases": [dict(item) for item in self.completed_phases],
        }

    def _complete_current_phase(self, now: float) -> None:
        if self.phase in {"ready", "failed"}:
            return
        self.completed_phases.append(
            {
                "phase": self.phase,
                "durationMs": round((now - self._phase_started_clock) * 1000, 3),
            }
        )


class SPAStaticFiles(StaticFiles):
    """Serve Vite assets while falling back to index.html for client routes."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        filename = path.rsplit("/", 1)[-1]
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in filename:
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and "." not in filename:
            return await super().get_response("index.html", scope)
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    startup_tracker = StartupTracker()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        scheduler_task: asyncio.Task[None] | None = None
        repository_watch_task: asyncio.Task[None] | None = None
        try:
            startup_tracker.enter("initializing_trust")
            trust_profile = TrustManager(repo_root=REPOSITORY_ROOT).initialize()
            startup_tracker.record_trust(trust_profile)
            startup_tracker.enter("configuring_database")
            configure_database(config.database_url)
            if config.environment == "test":
                create_schema()
            startup_tracker.enter("bootstrapping_database")
            with session_scope() as db:
                bootstrap_database(db, settings=config)
            startup_tracker.enter("recovering_worker")
            local_run_executor.configure(config, trust_profile=trust_profile)
            await local_run_executor.start()
            startup_tracker.enter("starting_scheduler")
            if config.environment != "test":
                scheduler_task = asyncio.create_task(
                    _scheduler_loop(), name="lumina-local-scheduler"
                )
                repository_watch_task = asyncio.create_task(
                    watch_repository_catalog(), name="lumina-extension-watcher"
                )
            startup_tracker.ready()
        except BaseException:
            startup_tracker.fail("BACKEND_STARTUP_FAILED")
            logger.exception(
                "Backend startup failed",
                extra={
                    "startup": startup_tracker.snapshot(
                        executor_started=local_run_executor.started
                    )
                },
            )
            raise
        try:
            yield
        finally:
            if scheduler_task is not None:
                scheduler_task.cancel()
                with suppress(asyncio.CancelledError):
                    await scheduler_task
            if repository_watch_task is not None:
                repository_watch_task.cancel()
                with suppress(asyncio.CancelledError):
                    await repository_watch_task
            await local_run_executor.stop()

    application = FastAPI(
        title="Lumina Agent API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if config.environment != "production" else None,
        openapi_url="/api/openapi.json",
    )
    application.state.settings = config
    application.state.startup_tracker = startup_tracker
    application.dependency_overrides[get_settings] = lambda: config
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "X-CSRF-Token",
            "Idempotency-Key",
            "If-Match",
            "X-Artifact-Draft-If-Match",
            "Last-Event-ID",
        ],
        expose_headers=["X-CSRF-Token", "ETag", "X-Request-ID", "Content-Disposition"],
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id[:120]
        started_at = perf_counter()
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request.state.request_id
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("Referrer-Policy", "same-origin")
            return response
        finally:
            route = request.scope.get("route")
            route_template = getattr(route, "path", None)
            logger.info(
                structured_event(
                    "http_request_completed",
                    request_id=request.state.request_id,
                    method=request.method,
                    path=request_log_path(
                        request.url.path,
                        route_template=(
                            route_template if isinstance(route_template, str) else None
                        ),
                    ),
                    status_code=status_code,
                    duration_ms=round((perf_counter() - started_at) * 1000, 3),
                )
            )

    install_error_handlers(application)
    for route_module in (
        auth,
        admin,
        admin_providers,
        projects,
        project_files,
        project_memberships,
        project_memories,
        conversations,
        deep_analysis,
        composer,
        extensions,
        finance,
        help,
        instructions,
        knowledge,
        mcp,
        messages,
        notifications,
        memories,
        runs,
        attachments,
        artifacts,
        providers,
        schedules,
        sharing,
    ):
        application.include_router(route_module.router, prefix="/api")
    application.include_router(runs.stream_router)

    @application.get("/api/health/live", tags=["health"])
    def liveness() -> dict[str, str]:
        return {
            "status": "ok",
            "executor": "running" if local_run_executor.started else "stopped",
        }

    @application.get("/api/health/ready", tags=["health"])
    def readiness() -> JSONResponse:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        if not local_run_executor.started:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "database": "ready",
                    "executor": "stopped",
                },
            )
        return JSONResponse(
            content={"status": "ok", "database": "ready", "executor": "ready"}
        )

    @application.get("/api/health/startup", tags=["health"])
    def startup_status() -> dict[str, Any]:
        return startup_tracker.snapshot(executor_started=local_run_executor.started)

    frontend_dist = REPOSITORY_ROOT / "apps" / "web" / "dist"
    if frontend_dist.is_dir():
        application.mount(
            "/",
            SPAStaticFiles(directory=frontend_dist, html=True),
            name="web",
        )

    return application


async def _scheduler_loop() -> None:
    while True:
        try:
            await local_scheduler.tick()
        except Exception:
            logger.exception("Scheduled task dispatch failed")
        await asyncio.sleep(15)


app = create_app()
