"""Authentication + authorization dependencies. Backend enforcement lives here;
UI hiding is never security. Every tenant-owned read filters by tenant_id."""

from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.engine import Connection, Engine

from .config import Settings
from .deps import settings_singleton
from .errors import AppError
from .security import hash_token
from .store import Store, reflect

SESSION_COOKIE = "tp_session"

MANAGE_MEMBERS = {"owner", "admin"}
WRITE = {"owner", "admin", "accountant", "reviewer"}
DECIDE = {"owner", "admin", "reviewer"}


@dataclass
class CurrentUser:
    user_id: str
    email: str
    tenant_id: str | None
    role: str | None
    session_id: str


def _engine(request: Request) -> Engine:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from .config import get_settings

        settings = get_settings()
        request.app.state.settings = settings
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        from .db import create_db_engine

        engine = create_db_engine(settings, connect_timeout=settings.probe_timeout_seconds)
        request.app.state.engine = engine
    return engine


def _token(request: Request, session_cookie: str | None, authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return session_cookie


def _store(request: Request) -> tuple[Store, Connection]:
    engine = _engine(request)
    conn = engine.connect()
    try:
        tables = reflect(engine)
    except Exception as exc:
        conn.close()
        raise AppError("INTERNAL_ERROR", "Service unavailable.") from exc
    return Store(conn, tables), conn


def get_current_user(
    request: Request,
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    token = _token(request, session_cookie, authorization)
    if not token:
        raise AppError("UNAUTHENTICATED", "Authentication required.")
    store, conn = _store(request)
    try:
        session = store.get_session(hash_token(token))
        if session is None:
            raise AppError("UNAUTHENTICATED", "Session expired or invalid.")
        user = store.get_user(str(session["user_id"]))
        if user is None or user["status"] != "active":
            raise AppError("UNAUTHENTICATED", "Session expired or invalid.")
        role = None
        tenant_id = session["active_tenant_id"]
        if tenant_id is not None:
            membership = store.get_membership(str(tenant_id), str(user["id"]))
            if membership is None:
                raise AppError("FORBIDDEN", "Workspace access revoked.")
            role = membership["role"]
        return CurrentUser(
            user_id=str(user["id"]),
            email=user["email"],
            tenant_id=str(tenant_id) if tenant_id else None,
            role=role,
            session_id=str(session["id"]),
        )
    finally:
        conn.close()


def require_tenant(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.tenant_id is None:
        raise AppError("FORBIDDEN", "No active workspace.")
    return user


def tenant_of(user: CurrentUser) -> str:
    """Tenant id narrowed for type-checking; require_tenant guarantees presence."""
    assert user.tenant_id is not None
    return user.tenant_id


def require_roles(*roles: str):  # type: ignore[no-untyped-def]
    def _check(user: CurrentUser = Depends(require_tenant)) -> CurrentUser:
        if user.role not in roles:
            raise AppError("FORBIDDEN", "Insufficient permissions.")
        return user

    return _check


def open_store(request: Request) -> tuple[Store, Connection, Settings]:
    """Transactional unit of work for routers: returns (store, conn); routers must
    commit on success and always close. Keeps handlers explicit and reviewable."""
    store, conn = _store(request)
    return store, conn, settings_singleton()


def correlation_of(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)
