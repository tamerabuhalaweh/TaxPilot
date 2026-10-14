"""Unit tests for the canonical snapshot + hash contract (no database)."""

from datetime import date, datetime

from app.snapshot import (
    ACCOUNTING_ONLY_DISCLAIMER,
    build_snapshot,
    canonical_json,
    snapshot_from_row,
    snapshot_hash,
)


def _base(**overrides):
    kwargs = {
        "tenant_id": "AAAAAAAA-1111-4111-8111-AAAAAAAAAAAA",
        "client_id": "BBBBBBBB-2222-4222-8222-BBBBBBBBBBBB",
        "subject_kind": "LEGAL_ENTITY",
        "subject_entity_id": "CCCCCCCC-3333-4333-8333-CCCCCCCCCCCC",
        "jurisdiction_code": "jo",
        "tax_type_code": "accounting_only",
        "regime_code": None,
        "obligation_profile_id": None,
        "profile_version": None,
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 12, 31),
        "context_revision": 1,
        "pack_version": None,
        "confirmation_status": "CONFIRMED",
        "confirmed_by": "DDDDDDDD-4444-4444-8444-DDDDDDDDDDDD",
        "confirmed_at": datetime(2026, 10, 12, 12, 0, 0),
        "created_at": datetime(2026, 10, 12, 11, 0, 0),
    }
    kwargs.update(overrides)
    return build_snapshot(**kwargs)


def test_canonical_form_normalizes_and_sorts():
    snap = _base()
    assert snap["jurisdiction_code"] == "JO"
    assert snap["tax_type_code"] == "ACCOUNTING_ONLY"
    assert snap["tenant_id"] == "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
    assert snap["snapshot_version"] == 1
    text = canonical_json(snap)
    assert text == canonical_json(dict(reversed(list(snap.items()))))
    assert ": " not in text and ", " not in text  # compact separators


def test_hash_deterministic_and_sensitive():
    first = snapshot_hash(_base())
    assert snapshot_hash(_base()) == first
    assert len(first) == 64
    for field, value in (
        ("period_end", date(2026, 6, 30)),
        ("context_revision", 2),
        ("confirmed_by", "EEEEEEEE-5555-4555-8555-EEEEEEEEEEEE"),
        ("client_id", "FFFFFFFF-6666-4666-8666-FFFFFFFFFFFF"),
        ("jurisdiction_code", "AE"),
    ):
        assert snapshot_hash(_base(**{field: value})) != first, field


def test_snapshot_from_row_accepts_api_shapes():
    snap = _base()
    row = dict(snap)
    row["period_start"] = "2026-01-01"
    row["confirmed_at"] = "2026-10-12T12:00:00"
    row["created_at"] = "2026-10-12T11:00:00"
    assert snapshot_hash(snapshot_from_row(row)) == snapshot_hash(snap)


def test_disclaimer_present():
    assert "ACCOUNTING_ONLY" in ACCOUNTING_ONLY_DISCLAIMER
    assert (
        "no tax" in ACCOUNTING_ONLY_DISCLAIMER.lower() or "compliance" in ACCOUNTING_ONLY_DISCLAIMER.lower()
    )
