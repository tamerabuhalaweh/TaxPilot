"""Database engine/session infrastructure. Tables arrive with domain migrations (Sprint 1+)."""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .config import Settings


def create_db_engine(settings: Settings, connect_timeout: float = 5.0):
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": connect_timeout},
    )


def session_factory(engine):  # type: ignore[no-untyped-def]
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def check_connectivity(engine) -> bool:  # type: ignore[no-untyped-def]
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
