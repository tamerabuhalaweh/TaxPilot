"""Liveness + readiness. Readiness never raises: degraded is an honest 200 with per-check flags."""

from fastapi import APIRouter, Request

from ..config import get_settings
from ..schemas.common import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=get_settings().app_name)


@router.get("/ready", response_model=ReadinessResponse)
def ready(request: Request) -> ReadinessResponse:
    queue = getattr(request.app.state, "queue_backend", "memory-fallback")
    database = getattr(request.app.state, "database_status", "unconfigured")
    status = "ready" if database in ("up", "unconfigured") else "degraded"
    return ReadinessResponse(status=status, database=database, queue=queue)  # type: ignore[arg-type]
