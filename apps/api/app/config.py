"""Centralized configuration. Secrets come from the environment; production refuses dev defaults."""

from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_DATABASE_URL = "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot"
_DEV_REDIS_URL = "redis://localhost:6379/0"

Environment = Literal["development", "staging", "test", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    app_name: str = "taxpilot-api"
    environment: Environment = "development"
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

    # Sprint 1 identity (FR-ID-001..009)
    password_min_length: int = 12
    session_ttl_hours: int = 24
    verification_ttl_hours: int = 48
    invite_ttl_hours: int = 72
    login_max_attempts: int = 5
    login_window_seconds: int = 900
    # Hosted demos run with registration closed: the seeded account is the only
    # way in. Default stays open for local development and test fixtures.
    allow_public_registration: bool = True
    # Optional shared secret required from the trusted web BFF. When set, every
    # route except health requires the matching header, so the API cannot be used
    # directly even if its public URL is discovered.
    api_edge_secret: str | None = None
    # Dev-only convenience (verification/invite token echo). None resolves to True
    # ONLY in explicitly local development; staging/production always refuse.
    auth_expose_tokens: bool | None = None
    # Backend JSON body cap (proxy enforces its own independently; uploads get
    # per-route limits later). Applies even without Content-Length.
    max_body_bytes: int = 1_048_576

    # EP-04B client-intake quarantine (FR-FILE-003..010). Uploads stream under
    # their own per-route cap; the global JSON body cap above is untouched.
    upload_max_bytes: int = 25 * 1024 * 1024
    # Only "local" exists (dev/test quarantine adapter). Staging/production
    # never accept local disk: storage readiness fails closed at request time
    # until an approved private object store + scan gate lands (EP-04C).
    storage_backend: str = "local"
    quarantine_root: str | None = None

    # REC-UI-01: restricted synthetic-demo reconciliation boundary. Off by
    # default and forced off in production. It accepts no uploaded files,
    # reads no quarantine, and persists nothing: fixtures are static and
    # versioned server-side, and the run is rebuilt in memory per request.
    demo_recon_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("TAXPILOT_DEMO_RECON_ENABLED", "DEMO_RECON_ENABLED"),
    )

    @model_validator(mode="after")
    def _guard(self) -> "Settings":
        if self.auth_expose_tokens is None:
            self.auth_expose_tokens = self.environment == "development"
        if self.environment == "production":
            if self.queue_backend == "memory":
                raise ValueError("production refuses the non-durable memory queue backend")
            if self.database_url == _DEV_DATABASE_URL or self.redis_url == _DEV_REDIS_URL:
                raise ValueError("production requires explicit DATABASE_URL and REDIS_URL (no dev defaults)")
            if not self.cors_allowed_origins:
                raise ValueError("production requires explicit cors_allowed_origins")
            if self.auth_expose_tokens:
                raise ValueError("production refuses auth_expose_tokens (verification/invite tokens)")
            # Never expose the synthetic demo boundary in production, regardless
            # of how the environment tries to set it.
            self.demo_recon_enabled = False
        if self.environment in ("staging", "production") and self.auth_expose_tokens:
            raise ValueError(f"{self.environment} refuses auth_expose_tokens")
        if self.api_edge_secret is not None and len(self.api_edge_secret) < 32:
            raise ValueError("api_edge_secret must be at least 32 characters when set")
        if self.queue_backend not in ("redis", "memory"):
            raise ValueError("queue_backend must be 'redis' or 'memory'")
        if self.storage_backend not in ("local",):
            raise ValueError("storage_backend must be 'local' (only dev/test adapter exists)")
        if self.upload_max_bytes < 1024:
            raise ValueError("upload_max_bytes is unreasonably small")
        return self

    @property
    def cookie_secure(self) -> bool:
        # Secure cookies everywhere except explicitly local development.
        return self.environment != "development"


def get_settings() -> Settings:
    return Settings()
