"""Centralized configuration. All secrets come from the environment; no defaults for credentials."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "taxpilot-api"
    environment: str = "development"  # development | staging | production
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot"
    redis_url: str = "redis://localhost:6379/0"

    # Queue behaviour (worker foundation; durable only when a real Redis is reachable)
    queue_default_max_attempts: int = 5


def get_settings() -> Settings:
    return Settings()
