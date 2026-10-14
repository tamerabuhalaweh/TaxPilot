"""Data access over explicit SQLAlchemy Core table definitions.

The schema is defined once, immutably, in code: no per-request reflection of a
shared global MetaData object, so concurrent requests cannot race on schema
state. `assert_schema_matches()` validates these definitions against a migrated
database (tests only — never on production request paths).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

tenants = Table(
    "tenants",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("plan_id", Text),
    Column("default_locale", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

users = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("email", Text, nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("email_verified", Boolean, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

memberships = Table(
    "tenant_memberships",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("role", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

invitations = Table(
    "invitations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("email", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("accepted_at", DateTime(timezone=True)),
    Column("created_by", UUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

sessions = Table(
    "user_sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("active_tenant_id", UUID(as_uuid=True)),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("csrf_hash", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("ip", Text),
    Column("user_agent", Text),
)

verifications = Table(
    "email_verifications",
    metadata,
    Column("token_hash", Text, primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

clients = Table(
    "clients",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("name", Text, nullable=False),
    Column("external_ref", Text),
    Column("sector", Text),
    Column("contact", Text),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

audit = Table(
    "audit_events",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True)),
    Column("actor_id", UUID(as_uuid=True)),
    Column("action", Text, nullable=False),
    Column("resource", Text),
    Column("request_id", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

# -- JUR-01 Phase 1 jurisdiction tables (migration 0004; no presences/groups) --
jurisdictions = Table(
    "jurisdiction_catalog",
    metadata,
    Column("code", Text, primary_key=True),
    Column("name_en", Text, nullable=False),
    Column("name_ar", Text, nullable=False),
    Column("availability", Text, nullable=False),
    Column("release_pack_version", Text),
    Column("capabilities", JSONB, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

legal_entities = Table(
    "legal_entities",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("client_id", UUID(as_uuid=True), nullable=False),
    Column("legal_name", Text, nullable=False),
    Column("incorporation_country_code", Text, nullable=False),
    Column("entity_type", Text, nullable=False),
    Column("legal_identifier_ciphertext", LargeBinary),
    Column("base_currency", Text, nullable=False),
    Column("fiscal_start", Text, nullable=False),
    Column("parent_legal_entity_id", UUID(as_uuid=True)),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

obligations = Table(
    "tax_obligation_profiles",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("client_id", UUID(as_uuid=True), nullable=False),
    Column("legal_entity_id", UUID(as_uuid=True), nullable=False),
    Column("jurisdiction_code", Text, nullable=False),
    Column("tax_type_code", Text, nullable=False),
    Column("regime_code", Text),
    Column("valid_from", Date, nullable=False),
    Column("valid_to", Date),
    Column("registration_status", Text, nullable=False),
    Column("verified_by", UUID(as_uuid=True)),
    Column("verified_at", DateTime(timezone=True)),
    Column("source_ref", Text),
    Column("version", Integer, nullable=False),
    Column("status", Text, nullable=False),
)

registrations = Table(
    "tax_registrations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("obligation_profile_id", UUID(as_uuid=True), nullable=False),
    Column("authority_code", Text, nullable=False),
    Column("registration_kind", Text, nullable=False),
    Column("number_ciphertext", LargeBinary),
    Column("number_nonce", LargeBinary),
    Column("number_last4", Text),
    Column("key_id", Text),
    Column("alg_version", Text, nullable=False),
    Column("starts_on", Date),
    Column("ends_on", Date),
    Column("status", Text, nullable=False),
    Column("version", Integer, nullable=False),
)

tax_contexts = Table(
    "tax_contexts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("client_id", UUID(as_uuid=True), nullable=False),
    Column("subject_kind", Text, nullable=False),
    Column("subject_entity_id", UUID(as_uuid=True)),
    Column("subject_group_id", UUID(as_uuid=True)),
    Column("obligation_profile_id", UUID(as_uuid=True)),
    Column("jurisdiction_code", Text, nullable=False),
    Column("tax_type_code", Text, nullable=False),
    Column("regime_code", Text),
    Column("period_start", Date, nullable=False),
    Column("period_end", Date, nullable=False),
    Column("profile_version", Integer),
    Column("context_revision", Integer, nullable=False),
    Column("pack_version", Text),
    Column("confirmation_status", Text, nullable=False),
    Column("context_hash", Text),
    Column("snapshot", JSONB),
    Column("confirmed_by", UUID(as_uuid=True)),
    Column("confirmed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

TABLES: dict[str, Table] = {
    "tenants": tenants,
    "users": users,
    "tenant_memberships": memberships,
    "invitations": invitations,
    "user_sessions": sessions,
    "email_verifications": verifications,
    "clients": clients,
    "audit_events": audit,
    "jurisdiction_catalog": jurisdictions,
    "legal_entities": legal_entities,
    "tax_obligation_profiles": obligations,
    "tax_registrations": registrations,
    "tax_contexts": tax_contexts,
}


def tables() -> dict:
    """Stable, thread-safe table definitions. No reflection, no global mutation."""
    return TABLES


def assert_schema_matches(engine) -> None:  # type: ignore[no-untyped-def]
    """Fail unless the migrated database matches these definitions (tests only)."""
    expected_type = {
        "UUID": "uuid",
        "Text": "text",
        "Boolean": "boolean",
        "DateTime": "timestamp with time zone",
        "Date": "date",
        "Integer": "integer",
        "LargeBinary": "bytea",
        "JSONB": "jsonb",
    }
    with engine.connect() as conn:
        for name, table in TABLES.items():
            cols = {
                r[0]: (r[1], r[2])
                for r in conn.execute(
                    text(
                        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                        "WHERE table_name = :t"
                    ),
                    {"t": name},
                ).fetchall()
            }
            if not cols:
                raise AssertionError(f"table missing from database: {name}")
            for column in table.columns:
                actual = cols.get(column.name)
                if actual is None:
                    raise AssertionError(f"{name}.{column.name} missing from database")
                want_type = expected_type[type(column.type).__name__]
                if actual[0] != want_type:
                    raise AssertionError(f"{name}.{column.name} type {actual[0]} != {want_type}")
                want_nullable = "YES" if column.nullable else "NO"
                if actual[1] != want_nullable:
                    raise AssertionError(f"{name}.{column.name} nullability {actual[1]} != {want_nullable}")
            # Reverse direction (PR-B hardening): every database column must be
            # defined in code, so an omitted column (unreadable/unwritable field)
            # fails loudly instead of surfacing as a runtime KeyError.
            defined = {column.name for column in table.columns}
            for actual_name in cols:
                if actual_name not in defined:
                    raise AssertionError(f"{name}.{actual_name} in database but missing from code")


def utcnow() -> datetime:
    return datetime.now(UTC)


def _row(mapping: Any) -> dict:
    data = dict(mapping)
    for key, value in list(data.items()):
        if isinstance(value, uuid.UUID):
            data[key] = str(value)
    return data


class Store:
    def __init__(self, conn, table_defs: dict):  # type: ignore[no-untyped-def]
        self.conn = conn
        self.t = table_defs

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
                .values(id=uuid.uuid4(), email=email, password_hash=password_hash)
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

    # -- verifications (atomic single-use claim) ------------------------------
    def save_verification(self, token_hash: str, user_id: str, expires_at: datetime) -> None:
        self.conn.execute(
            insert(self.t["email_verifications"]).values(
                token_hash=token_hash, user_id=user_id, expires_at=expires_at
            )
        )

    def claim_verification(self, token_hash: str) -> dict | None:
        """Atomically claim a verification token (FOR UPDATE + conditional UPDATE).
        Replay (sequential or concurrent) never re-verifies: second claim gets None."""
        row = (
            self.conn.execute(
                select(self.t["email_verifications"])
                .where(self.t["email_verifications"].c.token_hash == token_hash)
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if not row:
            return None
        data = _row(row)
        now = utcnow()
        if data["used_at"] is not None or data["expires_at"].replace(tzinfo=UTC) < now:
            return None
        updated = self.conn.execute(
            update(self.t["email_verifications"])
            .where(self.t["email_verifications"].c.token_hash == token_hash)
            .where(self.t["email_verifications"].c.used_at.is_(None))
            .values(used_at=now)
            .returning(self.t["email_verifications"].c.user_id)
        ).first()
        if updated is None:
            return None  # lost a concurrent race: the other claim won
        return data

    # -- tenants & memberships ----------------------------------------------
    def create_tenant(self, name: str, locale: str = "en") -> dict:
        row = (
            self.conn.execute(
                insert(self.t["tenants"])
                .values(id=uuid.uuid4(), name=name, default_locale=locale)
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
                .values(id=uuid.uuid4(), tenant_id=tenant_id, user_id=user_id, role=role)
                .returning(self.t["tenant_memberships"])
            )
            .mappings()
            .first()
        )
        return _row(row)

    def add_membership_idempotent(self, tenant_id: str, user_id: str, role: str) -> dict:
        """INSERT ... ON CONFLICT DO NOTHING + return row: safe under concurrent accept."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(self.t["tenant_memberships"])
            .values(id=uuid.uuid4(), tenant_id=tenant_id, user_id=user_id, role=role)
            .on_conflict_do_nothing(index_elements=["tenant_id", "user_id"])
            .returning(self.t["tenant_memberships"])
        )
        row = self.conn.execute(stmt).mappings().first()
        if row is None:  # already a member: return the existing row, no duplicate
            existing = (
                self.conn.execute(
                    select(self.t["tenant_memberships"])
                    .where(self.t["tenant_memberships"].c.tenant_id == tenant_id)
                    .where(self.t["tenant_memberships"].c.user_id == user_id)
                )
                .mappings()
                .first()
            )
            assert existing is not None
            return _row(existing)
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

    def get_membership_by_id(
        self, membership_id: str, tenant_id: str, for_update: bool = False
    ) -> dict | None:
        query = (
            select(self.t["tenant_memberships"])
            .where(self.t["tenant_memberships"].c.id == membership_id)
            .where(self.t["tenant_memberships"].c.tenant_id == tenant_id)
        )
        if for_update:
            query = query.with_for_update()
        row = self.conn.execute(query).mappings().first()
        return _row(row) if row else None

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

    def active_owner_count(self, tenant_id: str, lock: bool = False) -> int:
        """Count active owners; with lock=True take FOR UPDATE over the tenant's
        memberships so concurrent last-owner removals serialize (P0-A)."""
        query = (
            select(self.t["tenant_memberships"].c.id)
            .where(self.t["tenant_memberships"].c.tenant_id == tenant_id)
            .where(self.t["tenant_memberships"].c.role == "owner")
            .where(self.t["tenant_memberships"].c.status == "active")
        )
        if lock:
            query = query.with_for_update()
        return len(self.conn.execute(query).all())

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

    # -- invitations (atomic single-use claim) ---------------------------------
    def create_invitation(
        self, tenant_id: str, email: str, role: str, token_hash: str, expires_at: datetime, created_by: str
    ) -> dict:
        row = (
            self.conn.execute(
                insert(self.t["invitations"])
                .values(
                    id=uuid.uuid4(),
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

    def claim_invitation(self, token_hash: str) -> dict | None:
        """Lock the invitation row and claim it iff unused and unexpired.
        Returns the row (claimed by caller) or None. Caller inserts membership
        idempotently and stamps accepted_at before commit — one transaction."""
        row = (
            self.conn.execute(
                select(self.t["invitations"])
                .where(self.t["invitations"].c.token_hash == token_hash)
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if not row:
            return None
        data = _row(row)
        if data["accepted_at"] is not None:
            return None  # single-use: already consumed (replay handled by caller policy)
        if data["expires_at"].replace(tzinfo=UTC) < utcnow():
            return None
        return data

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
        csrf_hash: str,
        expires_at: datetime,
        ip: str | None,
        agent: str | None,
    ) -> dict:
        row = (
            self.conn.execute(
                insert(self.t["user_sessions"])
                .values(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    active_tenant_id=tenant_id,
                    token_hash=token_hash,
                    csrf_hash=csrf_hash,
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
        if not row or row["revoked_at"] is not None:
            return None
        expires = row["expires_at"]
        if expires.replace(tzinfo=UTC) < utcnow():
            return None
        return _row(row)

    def get_session_by_id(self, session_id: str) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["user_sessions"]).where(self.t["user_sessions"].c.id == session_id)
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

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
    def list_clients(self, tenant_id: str, status: str | None = "active") -> list[dict]:
        query = select(self.t["clients"]).where(self.t["clients"].c.tenant_id == tenant_id)
        if status is not None and status != "all":
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
                    id=uuid.uuid4(),
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

    # -- jurisdiction: legal entities (PR-B) ------------------------------------
    def create_legal_entity(
        self,
        tenant_id: str,
        client_id: str,
        legal_name: str,
        incorporation_country_code: str,
        base_currency: str,
        entity_type: str = "COMPANY",
        fiscal_start: str = "01-01",
        parent_legal_entity_id: str | None = None,
    ) -> dict:
        row = (
            self.conn.execute(
                insert(self.t["legal_entities"])
                .values(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    client_id=client_id,
                    legal_name=legal_name,
                    incorporation_country_code=incorporation_country_code,
                    entity_type=entity_type,
                    base_currency=base_currency,
                    fiscal_start=fiscal_start,
                    parent_legal_entity_id=parent_legal_entity_id,
                )
                .returning(self.t["legal_entities"])
            )
            .mappings()
            .first()
        )
        return _row(row)

    def get_legal_entity(self, entity_id: str, tenant_id: str) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["legal_entities"])
                .where(self.t["legal_entities"].c.id == entity_id)
                .where(self.t["legal_entities"].c.tenant_id == tenant_id)
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def list_legal_entities(
        self, tenant_id: str, client_id: str | None = None, status: str | None = None
    ) -> list[dict]:
        query = select(self.t["legal_entities"]).where(self.t["legal_entities"].c.tenant_id == tenant_id)
        if client_id is not None:
            query = query.where(self.t["legal_entities"].c.client_id == client_id)
        if status is not None and status != "all":
            query = query.where(self.t["legal_entities"].c.status == status)
        rows = self.conn.execute(query.order_by(self.t["legal_entities"].c.created_at)).mappings().all()
        return [_row(r) for r in rows]

    def update_legal_entity(self, entity_id: str, tenant_id: str, **fields: Any) -> dict | None:
        row = (
            self.conn.execute(
                update(self.t["legal_entities"])
                .where(self.t["legal_entities"].c.id == entity_id)
                .where(self.t["legal_entities"].c.tenant_id == tenant_id)
                .values(**fields)
                .returning(self.t["legal_entities"])
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    # -- jurisdiction: tax contexts (PR-B) --------------------------------------
    def create_tax_context(
        self,
        tenant_id: str,
        client_id: str,
        subject_entity_id: str,
        jurisdiction_code: str,
        tax_type_code: str,
        period_start: Any,
        period_end: Any,
        obligation_profile_id: str | None = None,
        regime_code: str | None = None,
        pack_version: str | None = None,
    ) -> dict:
        row = (
            self.conn.execute(
                insert(self.t["tax_contexts"])
                .values(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    client_id=client_id,
                    subject_kind="LEGAL_ENTITY",
                    subject_entity_id=subject_entity_id,
                    obligation_profile_id=obligation_profile_id,
                    jurisdiction_code=jurisdiction_code,
                    tax_type_code=tax_type_code,
                    regime_code=regime_code,
                    period_start=period_start,
                    period_end=period_end,
                    pack_version=pack_version,
                )
                .returning(self.t["tax_contexts"])
            )
            .mappings()
            .first()
        )
        return _row(row)

    def get_tax_context(self, context_id: str, tenant_id: str) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["tax_contexts"])
                .where(self.t["tax_contexts"].c.id == context_id)
                .where(self.t["tax_contexts"].c.tenant_id == tenant_id)
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def get_tax_context_for_update(self, context_id: str, tenant_id: str) -> dict | None:
        """Lock the context row (FOR UPDATE) and return the LIVE row.

        Callers must re-read after acquiring the lock: concurrent transitions
        serialize here, and the winner's commit is visible to the loser."""
        row = (
            self.conn.execute(
                select(self.t["tax_contexts"])
                .where(self.t["tax_contexts"].c.id == context_id)
                .where(self.t["tax_contexts"].c.tenant_id == tenant_id)
                .with_for_update()
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def list_tax_contexts(
        self,
        tenant_id: str,
        client_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        query = select(self.t["tax_contexts"]).where(self.t["tax_contexts"].c.tenant_id == tenant_id)
        if client_id is not None:
            query = query.where(self.t["tax_contexts"].c.client_id == client_id)
        if status is not None and status != "all":
            query = query.where(self.t["tax_contexts"].c.confirmation_status == status)
        rows = self.conn.execute(query.order_by(self.t["tax_contexts"].c.created_at)).mappings().all()
        return [_row(r) for r in rows]

    def update_tax_context(
        self, context_id: str, tenant_id: str, expect_status: str | None = None, **fields: Any
    ) -> dict | None:
        """Conditional update: with expect_status, the write applies only when the
        live row still holds that status (lost races return None instead of
        overwriting a concurrent transition)."""
        stmt = (
            update(self.t["tax_contexts"])
            .where(self.t["tax_contexts"].c.id == context_id)
            .where(self.t["tax_contexts"].c.tenant_id == tenant_id)
        )
        if expect_status is not None:
            stmt = stmt.where(self.t["tax_contexts"].c.confirmation_status == expect_status)
        row = self.conn.execute(stmt.values(**fields).returning(self.t["tax_contexts"])).mappings().first()
        return _row(row) if row else None

    # -- jurisdiction: obligations + registrations (reads; PR-B creates none) ---
    def get_obligation(self, obligation_id: str, tenant_id: str) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["tax_obligation_profiles"])
                .where(self.t["tax_obligation_profiles"].c.id == obligation_id)
                .where(self.t["tax_obligation_profiles"].c.tenant_id == tenant_id)
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    _REGISTRATION_MASK = (
        "id",
        "obligation_profile_id",
        "authority_code",
        "registration_kind",
        "number_last4",
        "status",
        "starts_on",
        "ends_on",
    )

    def _masked_registration(self, row: Any) -> dict:
        data = _row(row)
        return {k: data.get(k) for k in self._REGISTRATION_MASK}

    def list_registrations_masked(
        self, tenant_id: str, obligation_profile_id: str | None = None
    ) -> list[dict]:
        """Masked reads select ONLY safe columns: ciphertext, nonce, and key
        metadata never leave PostgreSQL on read paths (PR-B §5)."""
        table = self.t["tax_registrations"]
        query = select(*(table.c[k] for k in self._REGISTRATION_MASK)).where(table.c.tenant_id == tenant_id)
        if obligation_profile_id is not None:
            query = query.where(table.c.obligation_profile_id == obligation_profile_id)
        return [self._masked_registration(r) for r in self.conn.execute(query).mappings().all()]

    def get_registration_masked(self, registration_id: str, tenant_id: str) -> dict | None:
        table = self.t["tax_registrations"]
        row = (
            self.conn.execute(
                select(*(table.c[k] for k in self._REGISTRATION_MASK))
                .where(table.c.id == registration_id)
                .where(table.c.tenant_id == tenant_id)
            )
            .mappings()
            .first()
        )
        return self._masked_registration(row) if row else None

    # -- jurisdiction: catalog (read-only availability contract, PR-B §6) --------
    def list_jurisdictions(self) -> list[dict]:
        rows = (
            self.conn.execute(
                select(self.t["jurisdiction_catalog"]).order_by(self.t["jurisdiction_catalog"].c.code)
            )
            .mappings()
            .all()
        )
        return [_row(r) for r in rows]

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
                id=uuid.uuid4(),
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
