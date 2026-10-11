"""Authentication + authorization dependencies. Backend enforcement lives here;
UI hiding is never security. Every tenant-owned read filters by tenant_id.

Credential model (P0-C):
- Cookie-authenticated mutations require a session-bound CSRF token, plus Origin
  validation when the browser supplies Origin/Referer. Bearer-only requests (no
  session cookie present) follow a separate contract with no CSRF requirement.
- GET /auth/login, POST /auth/register, POST /auth/verify carry no session yet
  and are exempt by path.

Owner authority (P0-A): ownership is distinct from member administration.
Only an Owner may transfer ownership (explicit audited flow); Admins can manage
non-owner members but can never create, grant, demote, or remove owners, and no
change may leave a workspace without an active owner (transactionally enforced).
"""

from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.engine import Connection, Engine

from .config import Settings
from .deps import settings_singleton
from .errors import AppError
from .security import hash_token
from .store import Store
from .store import tables as _tables

SESSION_COOKIE = "tp_session"
CSRF_HEADER = "X-CSRF-Token"

MANAGE_MEMBERS = {"owner", "admin"}
WRITE = {"owner", "admin", "accountant", "reviewer"}
DECIDE = {"owner", "admin", "reviewer"}  # reserved for finding/approval routes

CSRF_EXEMPT_PATHS = {"/auth/login", "/auth/register", "/auth/verify"}


@dataclass
class CurrentUser:
    user_id: str
    email: str
    tenant_id: str | None
    role: str | None
    session_id: str
    auth_via: str  # "cookie" | "bearer" (cookie present wins: ambient authority)


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


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def get_current_user(
    request: Request,
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    bearer = _bearer(authorization)
    token = bearer or session_cookie
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
            auth_via="cookie" if session_cookie else "bearer",
        )
    finally:
        conn.close()


def _store(request: Request) -> tuple[Store, Connection]:
    engine = _engine(request)
    conn = engine.connect()
    return Store(conn, _tables()), conn


def _csrf_path_exempt(request: Request) -> bool:
    path = request.url.path
    prefix = getattr(request.app.state, "settings", None)
    api_prefix = prefix.api_v1_prefix if prefix else "/api/v1"
    if path.startswith(api_prefix):
        path = path[len(api_prefix) :]
    return path in CSRF_EXEMPT_PATHS


def enforce_csrf(request: Request, user: CurrentUser) -> CurrentUser:
    """Cookie-ambient mutations require proof of same-origin intent.

    - Safe methods and exempt auth paths: pass through.
    - Bearer-only callers (no session cookie): separate contract, no CSRF token.
    - Cookie callers on mutations: require the session-bound X-CSRF-Token AND,
      when the client supplies Origin/Referer, require an allowlisted origin.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return user
    if _csrf_path_exempt(request):
        return user
    if user.auth_via != "cookie":
        return user
    settings: Settings = getattr(request.app.state, "settings", None) or settings_singleton()
    presented = request.headers.get(CSRF_HEADER, "")
    if not presented:
        raise AppError("FORBIDDEN", "CSRF token required.")
    store, conn = _store(request)
    try:
        session = store.get_session_by_id(user.session_id)
        if session is None or session.get("csrf_hash") != hash_token(presented):
            raise AppError("FORBIDDEN", "Invalid CSRF token.")
    finally:
        conn.close()
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin and not _origin_allowed(origin, settings.cors_allowed_origins):
        raise AppError("FORBIDDEN", "Untrusted origin.")
    return user


def _origin_allowed(origin: str, allowed_origins: list[str]) -> bool:
    """Exact scheme://host[:port] match. Prefix matching would admit
    'https://app.example.com.evil.test' — never do that."""
    from urllib.parse import urlparse

    try:
        candidate = urlparse(origin)
        if not candidate.scheme or not candidate.hostname:
            return False
        identity = (candidate.scheme.lower(), candidate.hostname.lower(), candidate.port)
    except Exception:
        return False
    for allowed in allowed_origins:
        try:
            parsed = urlparse(allowed)
            if (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port) == identity:
                return True
        except Exception:
            continue
    return False


def require_tenant(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.tenant_id is None:
        raise AppError("FORBIDDEN", "No active workspace.")
    return user


def require_mutation(request: Request, user: CurrentUser = Depends(require_tenant)) -> CurrentUser:
    """Tenant membership + CSRF/origin enforcement for state-changing routes."""
    return enforce_csrf(request, user)


def require_roles(*roles: str):  # type: ignore[no-untyped-def]
    def _check(request: Request, user: CurrentUser = Depends(require_tenant)) -> CurrentUser:
        if user.role not in roles:
            raise AppError("FORBIDDEN", "Insufficient permissions.")
        return enforce_csrf(request, user)

    return _check


def tenant_of(user: CurrentUser) -> str:
    """Tenant id narrowed for type-checking; require_tenant guarantees presence."""
    assert user.tenant_id is not None
    return user.tenant_id


def open_store(request: Request) -> tuple[Store, Connection, Settings]:
    """Transactional unit of work for routers: returns (store, conn); routers must
    commit on success and always close. Keeps handlers explicit and reviewable."""
    store, conn = _store(request)
    return store, conn, settings_singleton()


def correlation_of(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)
