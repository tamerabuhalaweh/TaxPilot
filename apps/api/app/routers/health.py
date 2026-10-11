"""Liveness + readiness.

Liveness is cheap: the process answers. Readiness is honest: per-request bounded probes
of the configured dependencies; any required failure is HTTP 503 with per-check flags.
No connection strings or internals ever appear in these responses.
"""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config import get_settings
from ..probes import probe_database, probe_queue

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str = "0.1.0"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=get_settings().app_name)


@router.get("/ready")
def ready(request: Request) -> JSONResponse:
    database_up = probe_database(request.app)
    queue_state = probe_queue(request.app)
    try:
        environment = request.app.state.settings.environment
    except AttributeError:
        environment = get_settings().environment
    queue_ok = queue_state in ("up", "memory-fallback")
    ready_ok = database_up and queue_ok
    body = {
        "status": "ready" if ready_ok else "degraded",
        "environment": environment,
        "database": "up" if database_up else "down",
        "queue": queue_state,
    }
    # Development-only degraded operation is explicit via the environment field;
    # production still refuses memory-fallback at config load (see config.py).
    return JSONResponse(status_code=200 if ready_ok else 503, content=body)
