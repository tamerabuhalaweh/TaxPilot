"""Dependency-injection boundaries: services receive these, never module globals."""

from collections.abc import Iterator
from functools import lru_cache

from .config import Settings, get_settings


@lru_cache
def settings_singleton() -> Settings:
    return get_settings()


def get_db_settings() -> Settings:
    return settings_singleton()


def get_db_session() -> Iterator[None]:
    # Sprint 0: no domain tables yet; yields a session placeholder once migrations exist.
    # Routers must not import engines directly; they depend on this boundary.
    yield None
