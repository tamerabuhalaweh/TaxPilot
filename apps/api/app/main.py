"""FastAPI application factory. Versioned under /api/v1. No tax logic in Sprint 0."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import get_settings
from .db import create_db_engine
from .deps import settings_singleton
from .errors import AppError, app_error_handler, unhandled_handler
from .logging_setup import setup_logging
from .middleware import BodyLimitMiddleware, CorrelationIdMiddleware, EdgeTokenMiddleware
from .routers.auth import router as auth_router
from .routers.datasets import router as datasets_router
from .routers.engagements import router as engagements_router
from .routers.health import router as health_router
from .routers.intakes import router as intakes_router
from .routers.mappings import router as mappings_router
from .routers.workspace import router as workspace_router

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = settings_singleton()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Lazily created engine with bounded connect timeout; no probing at startup
        # so a down dependency delays readiness, never startup itself.
        engine = create_db_engine(settings, connect_timeout=settings.probe_timeout_seconds)
        app.state.engine = engine
        app.state.settings = settings
        log.info("startup environment=%s queue_backend=%s", settings.environment, settings.queue_backend)
        yield
        engine.dispose()
        log.info("shutdown engine disposed")

    app = FastAPI(title="TaxPilot API", version="0.1.0", lifespan=_lifespan)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    # Explicit allowlist only; credentials stay disabled (same-origin cookie
    # sessions need no CORS). X-CSRF-Token must be readable by the BFF, which is
    # same-origin too, so no exposed-headers entry is required.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID", "X-CSRF-Token", "Idempotency-Key"],
        max_age=600,
    )
    # Added last so it runs before body buffering and route work. Health stays
    # public for the hosting platform; everything else needs the BFF's header.
    app.add_middleware(EdgeTokenMiddleware, secret=settings.api_edge_secret)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_handler)

    app.include_router(health_router, prefix=settings.api_v1_prefix)
    app.include_router(auth_router, prefix=settings.api_v1_prefix)
    app.include_router(workspace_router, prefix=settings.api_v1_prefix)
    app.include_router(intakes_router, prefix=settings.api_v1_prefix)
    app.include_router(engagements_router, prefix=settings.api_v1_prefix)
    app.include_router(datasets_router, prefix=settings.api_v1_prefix)
    app.include_router(mappings_router, prefix=settings.api_v1_prefix)

    @app.get("/health", include_in_schema=False)
    def _root_health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def probe_database(app: FastAPI) -> bool:
    """Bounded liveness probe of the configured database. Never raises, never leaks DSN."""
    try:
        settings = app.state.settings
    except AttributeError:
        settings = get_settings()
    try:
        engine = getattr(app.state, "engine", None) or create_db_engine(
            settings, connect_timeout=settings.probe_timeout_seconds
        )
        created_here = not hasattr(app.state, "engine")
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        finally:
            if created_here:
                engine.dispose()
    except Exception:
        log.warning("database probe failed", exc_info=False)
        return False


def probe_queue(app: FastAPI) -> str:
    """Queue readiness reflecting the actual configured backend. Never raises."""
    try:
        settings = app.state.settings
    except AttributeError:
        settings = get_settings()
    if settings.queue_backend == "memory":
        return "memory-fallback"
    try:
        from worker.jobs import RedisBackend

        RedisBackend(settings.redis_url, socket_timeout=settings.probe_timeout_seconds)
        return "up"
    except Exception:
        log.warning("queue probe failed", exc_info=False)
        return "down"


app = create_app()
