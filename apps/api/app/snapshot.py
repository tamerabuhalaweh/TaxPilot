"""Canonical TaxContext snapshot + integrity hash (JUR PR-B).

Contract (Master SRS + JUR-IMPLEMENTATION-PLAN §5):
- The snapshot holds EVERY confirmed value: tenant, client, subject identity,
  jurisdiction/scope codes, obligation reference or explicit nulls, period,
  revision, pack version, confirmer + time, snapshot_version=1.
- Serialization is canonical: UTF-8 JSON, lexicographic keys, compact
  separators, UPPERCASED codes, lowercase UUIDs, ISO-8601 dates/timestamps.
- `snapshot_hash` = sha256 over the canonical bytes. It is INTEGRITY metadata
  only — never an authorization token, never accepted as a credential.
- Mutable display facts (legal names, currencies) are deliberately EXCLUDED:
  the snapshot pins identity (ids), never mutable descriptions.

Pure functions: no database, no settings. Fully unit-testable.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

SNAPSHOT_VERSION = 1

ACCOUNTING_ONLY_DISCLAIMER = (
    "ACCOUNTING_ONLY — accounting preparation only. This context asserts no tax "
    "compliance, no registration status, and no executable tax rules."
)


def _norm_code(value: str | None) -> str | None:
    return value.upper() if value is not None else None


def _norm_uuid(value: str | None) -> str | None:
    return str(value).lower() if value is not None else None


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value.isoformat()


def build_snapshot(
    *,
    tenant_id: str,
    client_id: str,
    subject_kind: str,
    subject_entity_id: str | None,
    jurisdiction_code: str,
    tax_type_code: str,
    regime_code: str | None,
    obligation_profile_id: str | None,
    profile_version: int | None,
    period_start: date,
    period_end: date,
    context_revision: int,
    pack_version: str | None,
    confirmation_status: str,
    confirmed_by: str | None,
    confirmed_at: datetime | None,
    created_at: datetime,
) -> dict[str, Any]:
    """Assemble the frozen snapshot dict (unsorted; canonicalized at hash time)."""
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "tenant_id": _norm_uuid(tenant_id),
        "client_id": _norm_uuid(client_id),
        "subject_kind": subject_kind,
        "subject_entity_id": _norm_uuid(subject_entity_id),
        "jurisdiction_code": _norm_code(jurisdiction_code),
        "tax_type_code": _norm_code(tax_type_code),
        "regime_code": _norm_code(regime_code),
        "obligation_profile_id": _norm_uuid(obligation_profile_id),
        "profile_version": profile_version,
        "period_start": _iso(period_start),
        "period_end": _iso(period_end),
        "context_revision": context_revision,
        "pack_version": pack_version,
        "confirmation_status": confirmation_status,
        "confirmed_by": _norm_uuid(confirmed_by),
        "confirmed_at": _iso(confirmed_at),
        "created_at": _iso(created_at),
    }


def canonical_json(snapshot: dict[str, Any]) -> str:
    """Canonical serialization: sorted keys, compact separators, UTF-8 str."""
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    """Deterministic sha256 hex over the canonical serialization."""
    return hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()


def snapshot_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the snapshot from a tax_contexts row mapping (DB or API shape).

    Accepts date/datetime objects or ISO strings for date fields.
    """

    def _date(value: Any) -> date:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        return date.fromisoformat(str(value))

    def _dt(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    created_at = _dt(row["created_at"])
    assert created_at is not None, "snapshot requires created_at"

    return build_snapshot(
        tenant_id=str(row["tenant_id"]),
        client_id=str(row["client_id"]),
        subject_kind=str(row["subject_kind"]),
        subject_entity_id=str(row["subject_entity_id"]) if row.get("subject_entity_id") else None,
        jurisdiction_code=str(row["jurisdiction_code"]),
        tax_type_code=str(row["tax_type_code"]),
        regime_code=row.get("regime_code"),
        obligation_profile_id=str(row["obligation_profile_id"]) if row.get("obligation_profile_id") else None,
        profile_version=row.get("profile_version"),
        period_start=_date(row["period_start"]),
        period_end=_date(row["period_end"]),
        context_revision=int(row["context_revision"]),
        pack_version=row.get("pack_version"),
        confirmation_status=str(row["confirmation_status"]),
        confirmed_by=str(row["confirmed_by"]) if row.get("confirmed_by") else None,
        confirmed_at=_dt(row.get("confirmed_at")),
        created_at=created_at,
    )
