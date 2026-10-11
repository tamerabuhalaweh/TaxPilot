"""Users, members, clients, audit routes. All tenant reads/writes are tenant-scoped;
cross-tenant object access returns 404 (no existence oracle)."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import IntegrityError

from ..deps import settings_singleton
from ..errors import AppError
from ..schemas.sprint1 import (
    AcceptInviteIn,
    AuditOut,
    ClientIn,
    ClientOut,
    ClientPatch,
    InviteIn,
    InviteOut,
    LoginOut,
    MemberOut,
    MemberPatch,
    MembershipOut,
)
from ..security import hash_token, new_token, normalize_email
from ..sprint1_auth import (
    MANAGE_MEMBERS,
    WRITE,
    CurrentUser,
    correlation_of,
    get_current_user,
    open_store,
    require_roles,
    require_tenant,
    tenant_of,
)
from ..store import utcnow

router = APIRouter(tags=["workspace"])


def _member_out(m: dict, email: str | None = None) -> MemberOut:
    return MemberOut(
        membership_id=str(m["id"]),
        user_id=str(m["user_id"]),
        email=email,
        role=m["role"],
        status=m["status"],
    )


@router.get("/users/me", response_model=LoginOut)
def me(request: Request, user: CurrentUser = Depends(get_current_user)) -> LoginOut:
    store, conn, _ = open_store(request)
    try:
        full = store.get_user(user.user_id)
        assert full is not None
        memberships = store.memberships_for_user(user.user_id)
    finally:
        conn.close()
    return LoginOut(
        user_id=str(full["id"]),
        email=full["email"],
        active_tenant_id=tenant_of(user),
        memberships=[MembershipOut(tenant_id=str(m["tenant_id"]), role=m["role"]) for m in memberships],
    )


# -- members ---------------------------------------------------------------
@router.get("/members", response_model=list[MemberOut])
def list_members(request: Request, user: CurrentUser = Depends(require_tenant)) -> list[MemberOut]:
    store, conn, _ = open_store(request)
    try:
        members = store.list_members(tenant_of(user))
        emails = {}
        for m in members:
            u = store.get_user(str(m["user_id"]))
            emails[str(m["user_id"])] = u["email"] if u else None
        return [_member_out(m, emails.get(str(m["user_id"]))) for m in members]
    finally:
        conn.close()


@router.post("/members/invitations", response_model=InviteOut, status_code=201)
def invite(
    body: InviteIn, request: Request, user: CurrentUser = Depends(require_roles(*MANAGE_MEMBERS))
) -> InviteOut:
    settings = settings_singleton()
    try:
        email = normalize_email(body.email)
    except ValueError as exc:
        raise AppError("VALIDATION_ERROR", str(exc)) from exc
    store, conn, _ = open_store(request)
    try:
        if (
            store.get_membership(tenant_of(user), user.user_id) is None
        ):  # pragma: no cover - guarded by dependency
            raise AppError("FORBIDDEN", "No workspace access.")
        token = new_token()
        inv = store.create_invitation(
            tenant_of(user),
            email,
            body.role,
            hash_token(token),
            utcnow() + timedelta(hours=settings.invite_ttl_hours),
            user.user_id,
        )
        store.audit(
            "member.invited",
            tenant_of(user),
            user.user_id,
            f"invitation:{inv['id']}",
            correlation_of(request),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return InviteOut(
        invitation_id=str(inv["id"]),
        email=email,
        role=body.role,
        expires_at=inv["expires_at"],
        token=token if settings.auth_expose_tokens else None,
    )


@router.post("/members/invitations/accept")
def accept(body: AcceptInviteIn, request: Request, user: CurrentUser = Depends(get_current_user)) -> dict:
    store, conn, _ = open_store(request)
    try:
        inv = store.get_invitation(hash_token(body.token.strip()))
        if inv is None or inv["accepted_at"] is not None or inv["expires_at"] < utcnow():
            raise AppError("VALIDATION_ERROR", "Invalid or expired invitation.")
        if inv["email"].lower() != user.email.lower():
            raise AppError("FORBIDDEN", "Invitation was issued to a different email address.")
        try:
            store.add_membership(str(inv["tenant_id"]), user.user_id, inv["role"])
        except IntegrityError:
            pass  # already a member: accepting again is a safe no-op
        store.accept_invitation(str(inv["id"]))
        store.audit(
            "member.accepted",
            str(inv["tenant_id"]),
            user.user_id,
            f"invitation:{inv['id']}",
            correlation_of(request),
        )
        conn.commit()
        tenant_id = str(inv["tenant_id"])
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"tenant_id": tenant_id}


@router.patch("/members/{membership_id}", response_model=MemberOut)
def patch_member(
    membership_id: str,
    body: MemberPatch,
    request: Request,
    user: CurrentUser = Depends(require_roles(*MANAGE_MEMBERS)),
) -> MemberOut:
    store, conn, _ = open_store(request)
    try:
        fields: dict = {}
        if body.role is not None:
            fields["role"] = body.role
        if body.status is not None:
            fields["status"] = body.status
        if not fields:
            raise AppError("VALIDATION_ERROR", "Nothing to update.")
        updated = store.update_membership(membership_id, tenant_of(user), **fields)
        if updated is None:
            raise AppError("NOT_FOUND", "Member not found.")
        if str(updated["user_id"]) == user.user_id and updated["status"] != "active":
            raise AppError("VALIDATION_ERROR", "You cannot deactivate your own access.")
        if body.role is not None:
            store.audit(
                "member.role_changed",
                tenant_of(user),
                user.user_id,
                f"membership:{membership_id}",
                correlation_of(request),
            )
        if body.status is not None:
            store.audit(
                "member.deactivated" if body.status != "active" else "member.reactivated",
                tenant_of(user),
                user.user_id,
                f"membership:{membership_id}",
                correlation_of(request),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return _member_out(updated)


# -- clients ---------------------------------------------------------------
def _client_out(c: dict) -> ClientOut:
    return ClientOut(
        id=str(c["id"]),
        name=c["name"],
        external_ref=c.get("external_ref"),
        sector=c.get("sector"),
        contact=c.get("contact"),
        status=c["status"],
    )


@router.get("/clients", response_model=list[ClientOut])
def list_clients(request: Request, user: CurrentUser = Depends(require_tenant)) -> list[ClientOut]:
    store, conn, _ = open_store(request)
    try:
        return [_client_out(c) for c in store.list_clients(tenant_of(user))]
    finally:
        conn.close()


@router.post("/clients", response_model=ClientOut, status_code=201)
def create_client(
    body: ClientIn, request: Request, user: CurrentUser = Depends(require_roles(*WRITE))
) -> ClientOut:
    store, conn, _ = open_store(request)
    try:
        client = store.create_client(
            tenant_of(user), body.name.strip(), body.external_ref, body.sector, body.contact
        )
        store.audit(
            "client.created", tenant_of(user), user.user_id, f"client:{client['id']}", correlation_of(request)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return _client_out(client)


@router.get("/clients/{client_id}", response_model=ClientOut)
def get_client(client_id: str, request: Request, user: CurrentUser = Depends(require_tenant)) -> ClientOut:
    store, conn, _ = open_store(request)
    try:
        client = store.get_client(client_id, tenant_of(user))
        if client is None:
            raise AppError("NOT_FOUND", "Client not found.")
        return _client_out(client)
    finally:
        conn.close()


@router.patch("/clients/{client_id}", response_model=ClientOut)
def patch_client(
    client_id: str, body: ClientPatch, request: Request, user: CurrentUser = Depends(require_roles(*WRITE))
) -> ClientOut:
    fields = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if "name" in fields:
        fields["name"] = fields["name"].strip()
    store, conn, _ = open_store(request)
    try:
        if not fields:
            existing = store.get_client(client_id, tenant_of(user))
            if existing is None:
                raise AppError("NOT_FOUND", "Client not found.")
            return _client_out(existing)
        updated = store.update_client(client_id, tenant_of(user), **fields)
        if updated is None:
            raise AppError("NOT_FOUND", "Client not found.")
        action = "client.archived" if fields.get("status") == "archived" else "client.updated"
        store.audit(action, tenant_of(user), user.user_id, f"client:{client_id}", correlation_of(request))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return _client_out(updated)


# -- audit -------------------------------------------------------------------
@router.get("/audit", response_model=list[AuditOut])
def list_audit(
    request: Request, user: CurrentUser = Depends(require_roles(*MANAGE_MEMBERS))
) -> list[AuditOut]:
    store, conn, _ = open_store(request)
    try:
        return [
            AuditOut(
                id=str(e["id"]),
                action=e["action"],
                actor_id=str(e["actor_id"]) if e["actor_id"] else None,
                resource=e.get("resource"),
                request_id=e.get("request_id"),
                created_at=e["created_at"],
            )
            for e in store.list_audit(tenant_of(user))
        ]
    finally:
        conn.close()
