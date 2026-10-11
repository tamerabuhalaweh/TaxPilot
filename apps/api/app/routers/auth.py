"""Auth routes: register, verify, login, logout, tenant switch.

Enumeration safety: unknown emails get neutral responses on reset-like paths;
login failures are generic (401) regardless of which half was wrong. Rate limits
return 429 with Retry-After; login resets counters on success.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from ..config import Settings
from ..deps import settings_singleton
from ..errors import AppError
from ..ratelimit import RedisRateLimiter
from ..schemas.sprint1 import (
    LoginIn,
    LoginOut,
    MembershipOut,
    RegisterIn,
    RegisterOut,
    SwitchTenantIn,
    VerifyIn,
)
from ..security import (
    hash_password,
    hash_token,
    new_token,
    normalize_email,
    validate_password,
    verify_password,
)
from ..sprint1_auth import SESSION_COOKIE, CurrentUser, correlation_of, get_current_user, open_store
from ..store import session_expiry, utcnow

router = APIRouter(tags=["auth"])

SESSION_TTL_HOURS_FALLBACK = 24


def _limiter(request: Request, settings: Settings) -> RedisRateLimiter:
    import redis as redis_lib

    client = redis_lib.Redis.from_url(settings.redis_url, socket_timeout=2)
    return RedisRateLimiter(client, settings.login_max_attempts, settings.login_window_seconds)


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _client_ip(request: Request) -> str:
    # Direct client IP only: never trust X-Forwarded-For (untrusted input, #36).
    return request.client.host if request.client else "unknown"


@router.post("/auth/register", response_model=RegisterOut, status_code=201)
def register(body: RegisterIn, request: Request, response: Response) -> RegisterOut:
    settings = settings_singleton()
    try:
        email = normalize_email(body.email)
        validate_password(body.password, settings.password_min_length)
    except ValueError as exc:
        raise AppError("VALIDATION_ERROR", str(exc)) from exc
    store, conn, _ = open_store(request)
    try:
        try:
            user = store.create_user(email, hash_password(body.password))
        except IntegrityError as exc:
            # Neutral-ish: do not reveal whether the email exists at registration.
            # (Login stays generic 401; see FR-ID-003 no-enumeration.)
            raise AppError("VALIDATION_ERROR", "Registration could not be completed.") from exc
        tenant = store.create_tenant(body.firm_name.strip() or "My firm")
        store.add_membership(str(tenant["id"]), str(user["id"]), "owner")
        token = new_token()
        store.save_verification(
            hash_token(token),
            str(user["id"]),
            utcnow() + timedelta(hours=settings.verification_ttl_hours),
        )
        store.audit(
            "user.registered",
            str(tenant["id"]),
            str(user["id"]),
            f"user:{user['id']}",
            correlation_of(request),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return RegisterOut(
        user_id=str(user["id"]),
        tenant_id=str(tenant["id"]),
        verification_token=token if settings.auth_expose_tokens else None,
    )


@router.post("/auth/verify")
def verify(body: VerifyIn, request: Request) -> dict:
    store, conn, _ = open_store(request)
    try:
        record = store.consume_verification(hash_token(body.token.strip()))
        if record is None:
            raise AppError("VALIDATION_ERROR", "Invalid or expired verification token.")
        store.mark_verified(str(record["user_id"]))
        store.audit(
            "user.verified",
            None,
            str(record["user_id"]),
            f"user:{record['user_id']}",
            correlation_of(request),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"verified": True}


@router.post("/auth/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, response: Response) -> LoginOut | JSONResponse:
    settings = settings_singleton()
    limiter = _limiter(request, settings)
    try:
        email = normalize_email(body.email)
    except ValueError:
        raise AppError("UNAUTHENTICATED", "Invalid email or password.") from None
    ident = email
    ip = _client_ip(request)
    try:
        if not limiter.allowed("login", ident) or not limiter.allowed("login-ip", ip):
            wait = limiter.retry_after("login", ident)
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "RATE_LIMITED", "message": "Too many attempts. Try again later."}},
                headers={"Retry-After": str(wait)},
            )
    except Exception as exc:  # limiter down -> fail closed, never bypass
        raise AppError("INTERNAL_ERROR", "Service unavailable.") from exc
    store, conn, _ = open_store(request)
    try:
        user = store.get_user_by_email(email)
        if (
            user is None
            or user["status"] != "active"
            or not verify_password(body.password, user["password_hash"])
        ):
            limiter.hit("login", ident)
            limiter.hit("login-ip", ip)
            raise AppError("UNAUTHENTICATED", "Invalid email or password.")
        if not user["email_verified"]:
            raise AppError("FORBIDDEN", "Email address is not verified.")
        memberships = store.memberships_for_user(str(user["id"]))
        active = memberships[0]["tenant_id"] if memberships else None
        token = new_token()
        store.create_session(
            str(user["id"]),
            str(active) if active else None,
            hash_token(token),
            session_expiry(settings.session_ttl_hours),
            ip,
            request.headers.get("user-agent"),
        )
        store.audit(
            "session.login",
            str(active) if active else None,
            str(user["id"]),
            f"user:{user['id']}",
            correlation_of(request),
        )
        conn.commit()
        limiter.reset("login", ident)
        limiter.reset("login-ip", ip)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _set_session_cookie(response, token, settings)
    return _login_out(user, memberships)


def _login_out(user: dict, memberships: list, active_id: str | None = None) -> LoginOut:
    first = str(memberships[0]["tenant_id"]) if memberships else None
    return LoginOut(
        user_id=str(user["id"]),
        email=user["email"],
        active_tenant_id=active_id or first,
        memberships=[MembershipOut(tenant_id=str(m["tenant_id"]), role=m["role"]) for m in memberships],
    )


@router.post("/auth/logout")
def logout(request: Request, response: Response, user: CurrentUser = Depends(get_current_user)) -> dict:
    store, conn, _ = open_store(request)
    try:
        store.revoke_session(user.session_id)
        store.audit(
            "session.logout",
            user.tenant_id,
            user.user_id,
            f"session:{user.session_id}",
            correlation_of(request),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"logged_out": True}


@router.post("/auth/tenant", response_model=LoginOut)
def switch_tenant(
    body: SwitchTenantIn, request: Request, response: Response, user: CurrentUser = Depends(get_current_user)
) -> LoginOut:
    settings = settings_singleton()
    store, conn, _ = open_store(request)
    try:
        membership = store.get_membership(body.tenant_id, user.user_id)
        if membership is None:
            raise AppError("FORBIDDEN", "No workspace access.")
        store.revoke_session(user.session_id)
        token = new_token()
        full_user = store.get_user(user.user_id)
        assert full_user is not None
        store.create_session(
            user.user_id,
            body.tenant_id,
            hash_token(token),
            session_expiry(settings.session_ttl_hours),
            _client_ip(request),
            request.headers.get("user-agent"),
        )
        store.audit(
            "session.tenant_switched",
            body.tenant_id,
            user.user_id,
            f"tenant:{body.tenant_id}",
            correlation_of(request),
        )
        conn.commit()
        memberships = store.memberships_for_user(user.user_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _set_session_cookie(response, token, settings)
    return _login_out(full_user, memberships, active_id=body.tenant_id)
