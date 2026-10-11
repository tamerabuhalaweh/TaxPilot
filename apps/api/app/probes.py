"""Dependency probes for readiness. Bounded, non-raising, DSN-free. No imports from main."""

import logging

from fastapi import FastAPI
from sqlalchemy import text

from .config import get_settings
from .db import create_db_engine

log = logging.getLogger(__name__)


def probe_database(app: FastAPI) -> bool:
    """True when a bounded SELECT succeeds. Never raises, never leaks the DSN."""
    try:
        settings = app.state.settings
    except AttributeError:
        settings = get_settings()
    engine = getattr(app.state, "engine", None)
    created_here = engine is None
    try:
        engine = engine or create_db_engine(settings, connect_timeout=settings.probe_timeout_seconds)
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
    """'up' | 'down' for redis; 'memory-fallback' when explicitly configured. Never raises."""
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
