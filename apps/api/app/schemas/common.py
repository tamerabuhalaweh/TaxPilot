"""Health contracts: liveness is cheap; readiness checks dependencies without leaking details."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str = "0.1.0"


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    database: Literal["up", "down", "unconfigured"]
    queue: Literal["up", "down", "memory-fallback"]
