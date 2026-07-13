from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
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
    extensions,
    finance,
    help,
    instructions,
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
from .db import SessionLocal, configure_database, create_schema
from .observability import request_log_path, structured_event
from .schedules.service import local_scheduler


logger = logging.getLogger(__name__)


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

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        configure_database(config.database_url)
        if config.environment == "test":
            create_schema()
        bootstrap_database(settings=config)
        local_run_executor.configure(config)
        await local_run_executor.start()
        scheduler_task: asyncio.Task[None] | None = None
        if config.environment != "test":
            scheduler_task = asyncio.create_task(
                _scheduler_loop(), name="lumina-local-scheduler"
            )
        try:
            yield
        finally:
            if scheduler_task is not None:
                scheduler_task.cancel()
                with suppress(asyncio.CancelledError):
                    await scheduler_task
            await local_run_executor.stop()

    application = FastAPI(
        title="Lumina Agent API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if config.environment != "production" else None,
        openapi_url="/api/openapi.json",
    )
    application.state.settings = config
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
        composer,
        extensions,
        finance,
        help,
        instructions,
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
    def readiness() -> dict[str, str] | JSONResponse:
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
        return {"status": "ok", "database": "ready", "executor": "ready"}

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
