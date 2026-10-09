"""FastAPI application factory. Versioned under /api/v1. No tax logic in Sprint 0."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import check_connectivity, create_db_engine
from .deps import settings_singleton
from .errors import AppError, app_error_handler, unhandled_handler
from .logging_setup import setup_logging
from .middleware import CorrelationIdMiddleware
from .routers.health import router as health_router

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = settings_singleton()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            engine = create_db_engine(settings)
            up = check_connectivity(engine)
            engine.dispose()
        except Exception:
            up = False
        app.state.database_status = "up" if up else "down"
        app.state.queue_backend = "memory-fallback"  # Redis probe happens on first enqueue
        log.info("startup probe database=%s", app.state.database_status)
        yield

    app = FastAPI(title="TaxPilot API", version="0.1.0", lifespan=_lifespan)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_handler)

    prefix = settings.api_v1_prefix
    app.include_router(health_router, prefix=prefix)

    @app.get("/health", include_in_schema=False)
    def _root_health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
