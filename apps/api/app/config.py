"""Centralized configuration. Secrets come from the environment; production refuses dev defaults."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_DATABASE_URL = "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot"
_DEV_REDIS_URL = "redis://localhost:6379/0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "taxpilot-api"
    environment: str = "development"  # development | staging | production
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    database_url: str = _DEV_DATABASE_URL
    redis_url: str = _DEV_REDIS_URL
    queue_backend: str = "redis"  # redis | memory (memory: explicit local/dev only, never production)

    cors_allowed_origins: list[str] = ["http://localhost:3000"]

    queue_default_max_attempts: int = 5
    probe_timeout_seconds: float = 2.0

    # Worker reliability (Sprint 0 foundation; production durability pending OPS-JOBS-01 #35)
    worker_lease_ttl_seconds: float = 60.0
    worker_recover_interval_seconds: float = 30.0
    jobs_durability_approved: bool = False

    @model_validator(mode="after")
    def _guard_production(self) -> "Settings":
        if self.environment == "production":
            if self.queue_backend == "memory":
                raise ValueError("production refuses the non-durable memory queue backend")
            if self.database_url == _DEV_DATABASE_URL or self.redis_url == _DEV_REDIS_URL:
                raise ValueError("production requires explicit DATABASE_URL and REDIS_URL (no dev defaults)")
            if not self.cors_allowed_origins:
                raise ValueError("production requires explicit cors_allowed_origins")
        if self.queue_backend not in ("redis", "memory"):
            raise ValueError("queue_backend must be 'redis' or 'memory'")
        return self


def get_settings() -> Settings:
    return Settings()
