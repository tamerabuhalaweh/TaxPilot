"""Data access over SQLAlchemy Core. Every tenant-owned query filters tenant_id;
object fetches return None across tenants (callers map to 404, never existence leaks)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import MetaData, insert, select, update

metadata = MetaData()


def reflect(engine):  # type: ignore[no-untyped-def]
    """Reflect Sprint 1 tables from a migrated database. Raises loudly if absent."""
    metadata.clear()
    metadata.reflect(
        engine,
        only=[
            "tenants",
            "users",
            "tenant_memberships",
            "invitations",
            "user_sessions",
            "email_verifications",
            "clients",
            "audit_events",
        ],
    )
    return {t.name: t for t in metadata.sorted_tables}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _row(mapping: Any) -> dict:
    return dict(mapping)


class Store:
    def __init__(self, conn, tables: dict):  # type: ignore[no-untyped-def]
        self.conn = conn
        self.t = tables

    # -- users -------------------------------------------------------------
    def get_user_by_email(self, email: str) -> dict | None:
        row = (
            self.conn.execute(select(self.t["users"]).where(self.t["users"].c.email == email))
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def get_user(self, user_id: str) -> dict | None:
        row = (
            self.conn.execute(select(self.t["users"]).where(self.t["users"].c.id == user_id))
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def create_user(self, email: str, password_hash: str) -> dict:
        row = (
            self.conn.execute(
                insert(self.t["users"])
                .values(id=str(uuid.uuid4()), email=email, password_hash=password_hash)
                .returning(self.t["users"])
            )
            .mappings()
            .first()
        )
        return _row(row)

    def mark_verified(self, user_id: str) -> None:
        self.conn.execute(
            update(self.t["users"]).where(self.t["users"].c.id == user_id).values(email_verified=True)
        )

    # -- verifications ------------------------------------------------------
    def save_verification(self, token_hash: str, user_id: str, expires_at: datetime) -> None:
        self.conn.execute(
            insert(self.t["email_verifications"]).values(
                token_hash=token_hash, user_id=user_id, expires_at=expires_at
            )
        )

    def consume_verification(self, token_hash: str) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["email_verifications"]).where(
                    self.t["email_verifications"].c.token_hash == token_hash
                )
            )
            .mappings()
            .first()
        )
        if not row:
            return None
        data = _row(row)
        if data["used_at"] is not None or data["expires_at"] < utcnow():
            return None
        self.conn.execute(
            update(self.t["email_verifications"])
            .where(self.t["email_verifications"].c.token_hash == token_hash)
            .values(used_at=utcnow())
        )
        return data

    # -- tenants & memberships ----------------------------------------------
    def create_tenant(self, name: str, locale: str = "en") -> dict:
        row = (
            self.conn.execute(
                insert(self.t["tenants"])
                .values(id=str(uuid.uuid4()), name=name, default_locale=locale)
                .returning(self.t["tenants"])
            )
            .mappings()
            .first()
        )
        return _row(row)

    def add_membership(self, tenant_id: str, user_id: str, role: str) -> dict:
        row = (
            self.conn.execute(
                insert(self.t["tenant_memberships"])
                .values(id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, role=role)
                .returning(self.t["tenant_memberships"])
            )
            .mappings()
            .first()
        )
        return _row(row)

    def memberships_for_user(self, user_id: str) -> list[dict]:
        rows = (
            self.conn.execute(
                select(self.t["tenant_memberships"]).where(self.t["tenant_memberships"].c.user_id == user_id)
            )
            .mappings()
            .all()
        )
        return [_row(r) for r in rows if r["status"] == "active"]

    def get_membership(self, tenant_id: str, user_id: str) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["tenant_memberships"])
                .where(self.t["tenant_memberships"].c.tenant_id == tenant_id)
                .where(self.t["tenant_memberships"].c.user_id == user_id)
            )
            .mappings()
            .first()
        )
        if not row or row["status"] != "active":
            return None
        return _row(row)

    def list_members(self, tenant_id: str) -> list[dict]:
        rows = (
            self.conn.execute(
                select(self.t["tenant_memberships"]).where(
                    self.t["tenant_memberships"].c.tenant_id == tenant_id
                )
            )
            .mappings()
            .all()
        )
        return [_row(r) for r in rows]

    def update_membership(self, membership_id: str, tenant_id: str, **fields: Any) -> dict | None:
        row = (
            self.conn.execute(
                update(self.t["tenant_memberships"])
                .where(self.t["tenant_memberships"].c.id == membership_id)
                .where(self.t["tenant_memberships"].c.tenant_id == tenant_id)
                .values(**fields)
                .returning(self.t["tenant_memberships"])
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    # -- invitations ---------------------------------------------------------
    def create_invitation(
        self, tenant_id: str, email: str, role: str, token_hash: str, expires_at: datetime, created_by: str
    ) -> dict:
        row = (
            self.conn.execute(
                insert(self.t["invitations"])
                .values(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    email=email,
                    role=role,
                    token_hash=token_hash,
                    expires_at=expires_at,
                    created_by=created_by,
                )
                .returning(self.t["invitations"])
            )
            .mappings()
            .first()
        )
        return _row(row)

    def get_invitation(self, token_hash: str) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["invitations"]).where(self.t["invitations"].c.token_hash == token_hash)
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def accept_invitation(self, invitation_id: str) -> None:
        self.conn.execute(
            update(self.t["invitations"])
            .where(self.t["invitations"].c.id == invitation_id)
            .values(accepted_at=utcnow())
        )

    # -- sessions -------------------------------------------------------------
    def create_session(
        self,
        user_id: str,
        tenant_id: str | None,
        token_hash: str,
        expires_at: datetime,
        ip: str | None,
        agent: str | None,
    ) -> dict:
        row = (
            self.conn.execute(
                insert(self.t["user_sessions"])
                .values(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    active_tenant_id=tenant_id,
                    token_hash=token_hash,
                    expires_at=expires_at,
                    ip=ip,
                    user_agent=(agent or "")[:300],
                )
                .returning(self.t["user_sessions"])
            )
            .mappings()
            .first()
        )
        return _row(row)

    def get_session(self, token_hash: str) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["user_sessions"]).where(self.t["user_sessions"].c.token_hash == token_hash)
            )
            .mappings()
            .first()
        )
        if not row or row["revoked_at"] is not None or row["expires_at"] < utcnow():
            return None
        return _row(row)

    def revoke_session(self, session_id: str) -> None:
        self.conn.execute(
            update(self.t["user_sessions"])
            .where(self.t["user_sessions"].c.id == session_id)
            .values(revoked_at=utcnow())
        )

    def revoke_user_sessions(self, user_id: str) -> None:
        self.conn.execute(
            update(self.t["user_sessions"])
            .where(self.t["user_sessions"].c.user_id == user_id)
            .values(revoked_at=utcnow())
        )

    # -- clients ---------------------------------------------------------------
    def list_clients(self, tenant_id: str, status: str | None = None) -> list[dict]:
        query = select(self.t["clients"]).where(self.t["clients"].c.tenant_id == tenant_id)
        if status:
            query = query.where(self.t["clients"].c.status == status)
        rows = self.conn.execute(query.order_by(self.t["clients"].c.created_at)).mappings().all()
        return [_row(r) for r in rows]

    def get_client(self, client_id: str, tenant_id: str) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["clients"])
                .where(self.t["clients"].c.id == client_id)
                .where(self.t["clients"].c.tenant_id == tenant_id)
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def create_client(
        self,
        tenant_id: str,
        name: str,
        external_ref: str | None = None,
        sector: str | None = None,
        contact: str | None = None,
    ) -> dict:
        row = (
            self.conn.execute(
                insert(self.t["clients"])
                .values(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    name=name,
                    external_ref=external_ref,
                    sector=sector,
                    contact=contact,
                )
                .returning(self.t["clients"])
            )
            .mappings()
            .first()
        )
        return _row(row)

    def update_client(self, client_id: str, tenant_id: str, **fields: Any) -> dict | None:
        row = (
            self.conn.execute(
                update(self.t["clients"])
                .where(self.t["clients"].c.id == client_id)
                .where(self.t["clients"].c.tenant_id == tenant_id)
                .values(**fields)
                .returning(self.t["clients"])
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    # -- audit ------------------------------------------------------------------
    def audit(
        self,
        action: str,
        tenant_id: str | None,
        actor_id: str | None,
        resource: str | None,
        request_id: str | None,
    ) -> None:
        self.conn.execute(
            insert(self.t["audit_events"]).values(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                actor_id=actor_id,
                action=action,
                resource=resource,
                request_id=request_id,
            )
        )

    def list_audit(self, tenant_id: str, limit: int = 100) -> list[dict]:
        rows = (
            self.conn.execute(
                select(self.t["audit_events"])
                .where(self.t["audit_events"].c.tenant_id == tenant_id)
                .order_by(self.t["audit_events"].c.created_at.desc())
                .limit(limit)
            )
            .mappings()
            .all()
        )
        return [_row(r) for r in rows]


def session_expiry(hours: int = 24) -> datetime:
    return utcnow() + timedelta(hours=hours)
