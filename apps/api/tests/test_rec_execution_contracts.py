"""REC-SLICE-03 unit contracts: eligibility precedence + run identity.

Pure domain only (no database): every gate code, evaluation precedence, and
identity stability rule is pinned here. Persistence-backed behavior is covered
by tests/integration/test_rec03_engagement_execution.py.
"""

from datetime import date

import pytest

from app.recon import (
    ELIGIBLE,
    ENGAGEMENT_NOT_ACTIVE,
    MISSING_DATASET_VERSION,
    OPERATION,
    SOURCE_NOT_RELEASED,
    UNAPPROVED_MAPPING,
    UNCONFIRMED_JURISDICTION,
    UNSUPPORTED_JOFO_PROFILE,
    EligibilitySnapshot,
    RunDescriptor,
    evaluate,
    payload_hash,
    source_set_fingerprint,
)

PERIOD = (date(2026, 1, 1), date(2026, 12, 31))

FULL = EligibilitySnapshot(
    engagement_active=True,
    jurisdiction_confirmed=True,
    sales_version_present=True,
    jofo_version_present=True,
    mapping_approved=True,
    source_released=True,
    jofo_profile_supported=True,
)


def _knockout(**kw) -> EligibilitySnapshot:
    base = {f: True for f in FULL.__dataclass_fields__}
    base.update(kw)
    return EligibilitySnapshot(**base)  # type: ignore[arg-type]


def test_all_gates_satisfied_is_eligible() -> None:
    decision = evaluate(FULL)
    assert decision == evaluate(EligibilitySnapshot(**{f: True for f in FULL.__dataclass_fields__}))
    assert decision.eligible is True
    assert decision.reason == ELIGIBLE


def test_empty_snapshot_denies_on_first_gate() -> None:
    decision = evaluate(EligibilitySnapshot())
    assert decision.eligible is False
    assert decision.reason == ENGAGEMENT_NOT_ACTIVE


@pytest.mark.parametrize(
    ("knockout", "reason"),
    [
        ({"engagement_active": False}, ENGAGEMENT_NOT_ACTIVE),
        ({"jurisdiction_confirmed": False}, UNCONFIRMED_JURISDICTION),
        ({"sales_version_present": False}, MISSING_DATASET_VERSION),
        ({"jofo_version_present": False}, MISSING_DATASET_VERSION),
        ({"mapping_approved": False}, UNAPPROVED_MAPPING),
        ({"source_released": False}, SOURCE_NOT_RELEASED),
        ({"jofo_profile_supported": False}, UNSUPPORTED_JOFO_PROFILE),
    ],
)
def test_each_gate_denies_with_stable_reason(knockout: dict, reason: str) -> None:
    decision = evaluate(_knockout(**knockout))
    assert decision.eligible is False
    assert decision.reason == reason


def test_precedence_engagement_before_jurisdiction_before_datasets() -> None:
    assert (
        evaluate(_knockout(engagement_active=False, jurisdiction_confirmed=False)).reason
        == ENGAGEMENT_NOT_ACTIVE
    )
    assert (
        evaluate(_knockout(jurisdiction_confirmed=False, sales_version_present=False)).reason
        == UNCONFIRMED_JURISDICTION
    )
    assert (
        evaluate(_knockout(sales_version_present=False, mapping_approved=False)).reason
        == MISSING_DATASET_VERSION
    )
    assert evaluate(_knockout(mapping_approved=False, source_released=False)).reason == UNAPPROVED_MAPPING
    assert (
        evaluate(_knockout(source_released=False, jofo_profile_supported=False)).reason == SOURCE_NOT_RELEASED
    )


def test_evaluate_rejects_non_snapshot() -> None:
    with pytest.raises(TypeError):
        evaluate("eligible")  # type: ignore[arg-type]


def _descriptor(**kw) -> RunDescriptor:
    base: dict = {
        "tenant_id": "tenant-1",
        "client_id": "client-1",
        "engagement_id": "eng-1",
        "operation": OPERATION,
        "idempotency_key": "run-key-1",
        "sales_dataset_version_id": "SALES-v3",
        "jofo_dataset_version_id": "JOFO-v3",
        "rules_version": "1",
        "projection_version": "1",
        "period_start": PERIOD[0],
        "period_end": PERIOD[1],
        "jurisdiction_code": "JO",
    }
    base.update(kw)
    return RunDescriptor(**base)


def test_run_identity_is_stable() -> None:
    assert payload_hash(_descriptor()) == payload_hash(_descriptor())
    assert len(payload_hash(_descriptor())) == 64


def test_run_identity_scopes_tenant_engagement_operation_key() -> None:
    base = payload_hash(_descriptor())
    assert payload_hash(_descriptor(tenant_id="tenant-2")) != base
    assert payload_hash(_descriptor(engagement_id="eng-2")) != base
    assert payload_hash(_descriptor(operation="other.op")) != base
    assert payload_hash(_descriptor(idempotency_key="run-key-2")) != base


def test_dataset_version_change_produces_new_identity() -> None:
    base = _descriptor()
    changed_sales = _descriptor(sales_dataset_version_id="SALES-v4")
    changed_jofo = _descriptor(jofo_dataset_version_id="JOFO-v4")
    assert payload_hash(changed_sales) != payload_hash(base)
    assert payload_hash(changed_jofo) != payload_hash(base)
    assert source_set_fingerprint("SALES-v4", "JOFO-v3") != source_set_fingerprint("SALES-v3", "JOFO-v3")


def test_source_set_fingerprint_is_key_independent() -> None:
    assert source_set_fingerprint("SALES-v3", "JOFO-v3") == source_set_fingerprint("SALES-v3", "JOFO-v3")
    assert len(source_set_fingerprint("SALES-v3", "JOFO-v3")) == 64


def test_blank_version_inputs_rejected() -> None:
    with pytest.raises(ValueError):
        source_set_fingerprint("  ", "JOFO-v3")
    with pytest.raises(ValueError):
        source_set_fingerprint("SALES-v3", "")
    with pytest.raises(TypeError):
        payload_hash("not-a-descriptor")  # type: ignore[arg-type]
