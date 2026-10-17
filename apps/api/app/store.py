"""Data access over explicit SQLAlchemy Core table definitions.

The schema is defined once, immutably, in code: no per-request reflection of a
shared global MetaData object, so concurrent requests cannot race on schema
state. `assert_schema_matches()` validates these definitions against a migrated
database (tests only — never on production request paths).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
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

# -- EP-04B client-intake quarantine metadata (migration 0005) --
document_intakes = Table(
    "document_intakes",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("client_id", UUID(as_uuid=True), nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("parent_id", UUID(as_uuid=True)),
    Column("duplicate_of", UUID(as_uuid=True)),
    Column("storage_key", Text, nullable=False),
    Column("content_sha256", Text, nullable=False),
    Column("byte_count", Integer, nullable=False),
    Column("filename", Text, nullable=False),
    Column("declared_type", Text, nullable=False),
    Column("content_type", Text),
    Column("status", Text, nullable=False),
    Column("reason", Text),
    Column("uploaded_by", UUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

# -- EP-04C1 durable processing jobs + transactional outbox (migration 0006) --
extraction_jobs = Table(
    "extraction_jobs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("client_id", UUID(as_uuid=True), nullable=False),
    Column("operation", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("payload_hash", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("lease_owner", Text, nullable=False),
    Column("fencing_token", Text, nullable=False),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("not_before", DateTime(timezone=True), nullable=False),
    Column("last_error", Text),
    Column("last_error_class", Text),
    Column("terminal_error", Text),
    Column("terminal_error_class", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

job_outbox = Table(
    "job_outbox",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("event_key", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("lease_owner", Text, nullable=False),
    Column("fencing_token", Text, nullable=False),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True)),
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

# -- REC-SLICE-03 engagement foundation + reconciliation-run boundary (0007) --
engagements = Table(
    "engagements",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("client_id", UUID(as_uuid=True), nullable=False),
    Column("review_type", Text, nullable=False),
    Column("period_start", Date, nullable=False),
    Column("period_end", Date, nullable=False),
    Column("status", Text, nullable=False),
    Column("assignee_user_id", UUID(as_uuid=True)),
    Column("tax_context_id", UUID(as_uuid=True)),
    Column("created_by", UUID(as_uuid=True)),
    Column("revision", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

engagement_events = Table(
    "engagement_events",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("engagement_id", UUID(as_uuid=True), nullable=False),
    Column("actor_id", UUID(as_uuid=True)),
    Column("action", Text, nullable=False),
    Column("prior_status", Text),
    Column("new_status", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

recon_runs = Table(
    "recon_runs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("client_id", UUID(as_uuid=True), nullable=False),
    Column("engagement_id", UUID(as_uuid=True), nullable=False),
    Column("operation", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("payload_hash", Text, nullable=False),
    Column("sales_dataset_version_id", Text, nullable=False),
    Column("jofo_dataset_version_id", Text, nullable=False),
    Column("source_set_fingerprint", Text, nullable=False),
    Column("rules_version", Text, nullable=False),
    Column("projection_version", Text, nullable=False),
    Column("period_start", Date),
    Column("period_end", Date),
    Column("jurisdiction_code", Text),
    Column("status", Text, nullable=False),
    Column("blocked_reason", Text, nullable=False),
    Column("blocked_detail", Text),
    Column("requested_by", UUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

# -- REC-DATA-01 client-scoped dataset-version registry (0008) -----------------
dataset_versions = Table(
    "dataset_versions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("client_id", UUID(as_uuid=True), nullable=False),
    Column("source_intake_id", UUID(as_uuid=True), nullable=False),
    Column("doc_type", Text, nullable=False),
    Column("declared_format", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("parent_version_id", UUID(as_uuid=True)),
    Column("source_content_sha256", Text, nullable=False),
    Column("parser_version", Text),
    Column("normalization_version", Text),
    Column("mapping_revision", Text),
    Column("dataset_fingerprint", Text),
    Column("registration_fingerprint", Text, nullable=False),
    Column("registered_by", UUID(as_uuid=True)),
    Column("registered_at", DateTime(timezone=True), nullable=False),
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
    "document_intakes": document_intakes,
    "extraction_jobs": extraction_jobs,
    "job_outbox": job_outbox,
    "jurisdiction_catalog": jurisdictions,
    "legal_entities": legal_entities,
    "tax_obligation_profiles": obligations,
    "tax_registrations": registrations,
    "tax_contexts": tax_contexts,
    "engagements": engagements,
    "engagement_events": engagement_events,
    "recon_runs": recon_runs,
    "dataset_versions": dataset_versions,
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

    # -- engagements (REC-SLICE-03 foundation) ----------------------------------
    def create_engagement(
        self,
        tenant_id: str,
        client_id: str,
        review_type: str,
        period_start: date,
        period_end: date,
        assignee_user_id: str | None = None,
        tax_context_id: str | None = None,
        created_by: str | None = None,
    ) -> dict:
        row = (
            self.conn.execute(
                insert(self.t["engagements"])
                .values(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    client_id=client_id,
                    review_type=review_type,
                    period_start=period_start,
                    period_end=period_end,
                    status="DRAFT",
                    assignee_user_id=assignee_user_id,
                    tax_context_id=tax_context_id,
                    created_by=created_by,
                )
                .returning(self.t["engagements"])
            )
            .mappings()
            .first()
        )
        return _row(row)

    def get_engagement(self, engagement_id: str, tenant_id: str) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["engagements"])
                .where(self.t["engagements"].c.id == engagement_id)
                .where(self.t["engagements"].c.tenant_id == tenant_id)
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def list_engagements(
        self,
        tenant_id: str,
        client_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        query = select(self.t["engagements"]).where(self.t["engagements"].c.tenant_id == tenant_id)
        if client_id is not None:
            query = query.where(self.t["engagements"].c.client_id == client_id)
        if status is not None:
            query = query.where(self.t["engagements"].c.status == status)
        rows = self.conn.execute(query.order_by(self.t["engagements"].c.created_at)).mappings().all()
        return [_row(r) for r in rows]

    def find_engagement_duplicate(
        self,
        tenant_id: str,
        client_id: str,
        period_start: date,
        period_end: date,
        review_type: str,
    ) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["engagements"])
                .where(self.t["engagements"].c.tenant_id == tenant_id)
                .where(self.t["engagements"].c.client_id == client_id)
                .where(self.t["engagements"].c.period_start == period_start)
                .where(self.t["engagements"].c.period_end == period_end)
                .where(self.t["engagements"].c.review_type == review_type)
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def update_engagement(
        self,
        engagement_id: str,
        tenant_id: str,
        expected_status: str,
        expected_revision: int,
        **fields: Any,
    ) -> dict | None:
        """Compare-and-swap engagement mutation (concurrency integrity).

        The UPDATE predicates on the observed (status, revision): a concurrent
        writer that committed first bumps revision, so a stale second writer
        matches zero rows and the caller fails closed (409) without writing
        history. Returns the updated row, or None on conflict/gone.
        """
        table = self.t["engagements"]
        row = (
            self.conn.execute(
                update(table)
                .where(table.c.id == engagement_id)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.status == expected_status)
                .where(table.c.revision == expected_revision)
                .values(**fields, revision=table.c.revision + 1, updated_at=utcnow())
                .returning(table)
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def add_engagement_event(
        self,
        tenant_id: str,
        engagement_id: str,
        actor_id: str | None,
        action: str,
        prior_status: str | None = None,
        new_status: str | None = None,
    ) -> dict:
        row = (
            self.conn.execute(
                insert(self.t["engagement_events"])
                .values(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    engagement_id=engagement_id,
                    actor_id=actor_id,
                    action=action,
                    prior_status=prior_status,
                    new_status=new_status,
                )
                .returning(self.t["engagement_events"])
            )
            .mappings()
            .first()
        )
        return _row(row)

    def list_engagement_events(self, engagement_id: str, tenant_id: str) -> list[dict]:
        rows = (
            self.conn.execute(
                select(self.t["engagement_events"])
                .where(self.t["engagement_events"].c.engagement_id == engagement_id)
                .where(self.t["engagement_events"].c.tenant_id == tenant_id)
                .order_by(self.t["engagement_events"].c.created_at)
            )
            .mappings()
            .all()
        )
        return [_row(r) for r in rows]

    def get_tax_context(self, context_id: str, tenant_id: str) -> dict | None:
        """Read-only verification access to jurisdiction contexts (writes are
        owned by the jurisdiction slice; this slice never mutates them)."""
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

    # -- reconciliation runs (REC-SLICE-03 boundary) ---------------------------
    def lock_run_key(self, tenant_id: str, engagement_id: str, operation: str, key: str) -> None:
        """Serialize concurrent run requests sharing one idempotency identity.

        Transaction-scoped advisory lock: concurrent same-key requests queue
        here, so the check-then-insert below never doubles (intake pattern).
        """
        self.conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"recon-run:{tenant_id}:{engagement_id}:{operation}:{key}"},
        )

    def get_runs_by_key(self, tenant_id: str, engagement_id: str, operation: str, key: str) -> list[dict]:
        rows = (
            self.conn.execute(
                select(self.t["recon_runs"])
                .where(self.t["recon_runs"].c.tenant_id == tenant_id)
                .where(self.t["recon_runs"].c.engagement_id == engagement_id)
                .where(self.t["recon_runs"].c.operation == operation)
                .where(self.t["recon_runs"].c.idempotency_key == key)
                .order_by(self.t["recon_runs"].c.created_at)
            )
            .mappings()
            .all()
        )
        return [_row(r) for r in rows]

    def create_run(
        self,
        tenant_id: str,
        client_id: str,
        engagement_id: str,
        operation: str,
        idempotency_key: str,
        payload_hash: str,
        sales_dataset_version_id: str,
        jofo_dataset_version_id: str,
        source_set_fingerprint: str,
        rules_version: str,
        projection_version: str,
        period_start: date | None,
        period_end: date | None,
        jurisdiction_code: str | None,
        blocked_reason: str,
        blocked_detail: str | None,
        requested_by: str | None,
    ) -> dict:
        row = (
            self.conn.execute(
                insert(self.t["recon_runs"])
                .values(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    client_id=client_id,
                    engagement_id=engagement_id,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                    sales_dataset_version_id=sales_dataset_version_id,
                    jofo_dataset_version_id=jofo_dataset_version_id,
                    source_set_fingerprint=source_set_fingerprint,
                    rules_version=rules_version,
                    projection_version=projection_version,
                    period_start=period_start,
                    period_end=period_end,
                    jurisdiction_code=jurisdiction_code,
                    status="BLOCKED",
                    blocked_reason=blocked_reason,
                    blocked_detail=blocked_detail,
                    requested_by=requested_by,
                )
                .returning(self.t["recon_runs"])
            )
            .mappings()
            .first()
        )
        return _row(row)

    def get_run(self, run_id: str, tenant_id: str) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["recon_runs"])
                .where(self.t["recon_runs"].c.id == run_id)
                .where(self.t["recon_runs"].c.tenant_id == tenant_id)
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def list_runs(self, engagement_id: str, tenant_id: str) -> list[dict]:
        rows = (
            self.conn.execute(
                select(self.t["recon_runs"])
                .where(self.t["recon_runs"].c.engagement_id == engagement_id)
                .where(self.t["recon_runs"].c.tenant_id == tenant_id)
                .order_by(self.t["recon_runs"].c.created_at)
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

    # -- document intakes (EP-04B quarantine metadata) ---------------------------
    def lock_intake_key(self, tenant_id: str, client_id: str, key: str) -> None:
        """Serialize concurrent uploads sharing one idempotency key.

        Transaction-scoped advisory lock over (tenant, client, key): concurrent
        same-key uploads queue here, so version assignment below never doubles.
        """
        self.conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"intake:{tenant_id}:{client_id}:{key}"},
        )

    def get_intakes_by_key(
        self, tenant_id: str, client_id: str, key: str, for_update: bool = False
    ) -> list[dict]:
        query = (
            select(self.t["document_intakes"])
            .where(self.t["document_intakes"].c.tenant_id == tenant_id)
            .where(self.t["document_intakes"].c.client_id == client_id)
            .where(self.t["document_intakes"].c.idempotency_key == key)
            .order_by(self.t["document_intakes"].c.version)
        )
        if for_update:
            query = query.with_for_update()
        return [_row(r) for r in self.conn.execute(query).mappings().all()]

    def find_intakes_by_sha(self, tenant_id: str, client_id: str, sha: str) -> list[dict]:
        rows = (
            self.conn.execute(
                select(self.t["document_intakes"])
                .where(self.t["document_intakes"].c.tenant_id == tenant_id)
                .where(self.t["document_intakes"].c.client_id == client_id)
                .where(self.t["document_intakes"].c.content_sha256 == sha)
                .order_by(self.t["document_intakes"].c.created_at)
                .limit(5)
            )
            .mappings()
            .all()
        )
        return [_row(r) for r in rows]

    def get_intake(self, intake_id: str, tenant_id: str) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["document_intakes"])
                .where(self.t["document_intakes"].c.id == intake_id)
                .where(self.t["document_intakes"].c.tenant_id == tenant_id)
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def list_intakes(self, client_id: str, tenant_id: str, limit: int = 100) -> list[dict]:
        rows = (
            self.conn.execute(
                select(self.t["document_intakes"])
                .where(self.t["document_intakes"].c.client_id == client_id)
                .where(self.t["document_intakes"].c.tenant_id == tenant_id)
                .order_by(self.t["document_intakes"].c.created_at.desc())
                .limit(limit)
            )
            .mappings()
            .all()
        )
        return [_row(r) for r in rows]

    def create_intake(
        self,
        tenant_id: str,
        client_id: str,
        key: str,
        version: int,
        parent_id: str | None,
        duplicate_of: str | None,
        storage_key: str,
        sha: str,
        byte_count: int,
        filename: str,
        declared_type: str,
        content_type: str | None,
        uploaded_by: str,
    ) -> dict:
        row = (
            self.conn.execute(
                insert(self.t["document_intakes"])
                .values(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    client_id=client_id,
                    idempotency_key=key,
                    version=version,
                    parent_id=parent_id,
                    duplicate_of=duplicate_of,
                    storage_key=storage_key,
                    content_sha256=sha,
                    byte_count=byte_count,
                    filename=filename,
                    declared_type=declared_type,
                    content_type=content_type,
                    status="QUARANTINED",
                    uploaded_by=uploaded_by,
                )
                .returning(self.t["document_intakes"])
            )
            .mappings()
            .first()
        )
        return _row(row)

    # -- dataset versions (REC-DATA-01 client-scoped registry) -------------------
    def lock_dataset_key(self, tenant_id: str, client_id: str, source_intake_id: str, doc_type: str) -> None:
        """Serialize concurrent registrations sharing one source scope.

        Transaction-scoped advisory lock over (tenant, client, source intake,
        document type): concurrent same-identity registrations queue here, so
        version assignment below never doubles (intake pattern).
        """
        self.conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"dataset:{tenant_id}:{client_id}:{source_intake_id}:{doc_type}"},
        )

    def get_dataset_versions_by_source(
        self,
        tenant_id: str,
        client_id: str,
        source_intake_id: str,
        doc_type: str,
        for_update: bool = False,
    ) -> list[dict]:
        query = (
            select(self.t["dataset_versions"])
            .where(self.t["dataset_versions"].c.tenant_id == tenant_id)
            .where(self.t["dataset_versions"].c.client_id == client_id)
            .where(self.t["dataset_versions"].c.source_intake_id == source_intake_id)
            .where(self.t["dataset_versions"].c.doc_type == doc_type)
            .order_by(self.t["dataset_versions"].c.version)
        )
        if for_update:
            query = query.with_for_update()
        return [_row(r) for r in self.conn.execute(query).mappings().all()]

    def get_dataset_version(self, version_id: str, tenant_id: str) -> dict | None:
        row = (
            self.conn.execute(
                select(self.t["dataset_versions"])
                .where(self.t["dataset_versions"].c.id == version_id)
                .where(self.t["dataset_versions"].c.tenant_id == tenant_id)
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def list_dataset_versions(
        self,
        tenant_id: str,
        client_id: str | None = None,
        doc_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        query = select(self.t["dataset_versions"]).where(self.t["dataset_versions"].c.tenant_id == tenant_id)
        if client_id is not None:
            query = query.where(self.t["dataset_versions"].c.client_id == client_id)
        if doc_type is not None:
            query = query.where(self.t["dataset_versions"].c.doc_type == doc_type)
        rows = (
            self.conn.execute(query.order_by(self.t["dataset_versions"].c.registered_at.desc()).limit(limit))
            .mappings()
            .all()
        )
        return [_row(r) for r in rows]

    def register_dataset_version(
        self,
        *,
        tenant_id: str,
        client_id: str,
        source_intake_id: str,
        doc_type: str,
        declared_format: str,
        source_content_sha256: str,
        registration_fingerprint: str,
        parser_version: str | None = None,
        normalization_version: str | None = None,
        mapping_revision: str | None = None,
        dataset_fingerprint: str | None = None,
        registered_by: str | None = None,
    ) -> tuple[dict, bool]:
        """Idempotently register one immutable dataset version.

        Returns ``(row, created)``. Concurrent/repeated calls with the same
        identity converge on the existing row; a different identity for the
        same (source intake, document type) raises ``ValueError`` (fail closed,
        never overwrite). This is the internal persistence primitive: the
        authenticated POST refuses until release evidence exists, so no row is
        ever created from the API yet.
        """
        self.lock_dataset_key(tenant_id, client_id, source_intake_id, doc_type)
        existing = self.get_dataset_versions_by_source(
            tenant_id, client_id, source_intake_id, doc_type, for_update=True
        )
        if existing:
            if existing[0]["registration_fingerprint"] == registration_fingerprint:
                return existing[0], False
            raise ValueError("dataset version identity conflict for this source intake and document type")
        latest = (
            self.conn.execute(
                select(self.t["dataset_versions"])
                .where(self.t["dataset_versions"].c.tenant_id == tenant_id)
                .where(self.t["dataset_versions"].c.client_id == client_id)
                .where(self.t["dataset_versions"].c.doc_type == doc_type)
                .order_by(self.t["dataset_versions"].c.version.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        version = (latest["version"] + 1) if latest else 1
        parent_version_id = latest["id"] if latest else None
        row = (
            self.conn.execute(
                insert(self.t["dataset_versions"])
                .values(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    client_id=client_id,
                    source_intake_id=source_intake_id,
                    doc_type=doc_type,
                    declared_format=declared_format,
                    version=version,
                    parent_version_id=parent_version_id,
                    source_content_sha256=source_content_sha256,
                    parser_version=parser_version,
                    normalization_version=normalization_version,
                    mapping_revision=mapping_revision,
                    dataset_fingerprint=dataset_fingerprint,
                    registration_fingerprint=registration_fingerprint,
                    registered_by=registered_by,
                )
                .returning(self.t["dataset_versions"])
            )
            .mappings()
            .first()
        )
        return _row(row), True


def session_expiry(hours: int = 24) -> datetime:
    return utcnow() + timedelta(hours=hours)
