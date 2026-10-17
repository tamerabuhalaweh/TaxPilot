"""REC-DATA-01 unit contracts: registration precondition + derived eligibility.

Pure domain only (no database). Pins the default-deny registration order, the
distinct-hash rule (an absent ``dataset_fingerprint`` always blocks derived
eligibility), and identity stability. Persistence-backed behavior lives in
tests/integration/test_rec_data01_dataset_versions.py.
"""

from app.datasets.registry import (
    ELIGIBLE,
    GENERAL_LEDGER,
    JOFOTARA_EXPORT,
    KNOWN_DOCUMENT_TYPES,
    KNOWN_FORMATS,
    MISSING_DATASET_FINGERPRINT,
    SALES_REGISTER,
    SOURCE_NOT_RELEASED,
    UNAPPROVED_MAPPING,
    UNSUPPORTED_DOCUMENT_TYPE,
    UNSUPPORTED_FORMAT,
    derive_eligibility,
    evaluate_registration,
    registration_identity,
)

SHA = "a" * 64
FP = "b" * 64


def _identity(**overrides: str | None) -> str:
    base = {
        "tenant_id": "t1",
        "client_id": "c1",
        "source_intake_id": "s1",
        "doc_type": SALES_REGISTER,
        "declared_format": "csv",
        "source_content_sha256": SHA,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return registration_identity(**base)  # type: ignore[arg-type]


def test_known_vocabularies_are_pinned() -> None:
    assert KNOWN_DOCUMENT_TYPES == (SALES_REGISTER, GENERAL_LEDGER, JOFOTARA_EXPORT)
    assert KNOWN_FORMATS == ("csv", "xlsx")


def test_registration_refuses_unsupported_document_type_first() -> None:
    d = evaluate_registration(doc_type="bank_statement", declared_format="csv", source_status="QUARANTINED")
    assert (d.allowed, d.reason) == (False, UNSUPPORTED_DOCUMENT_TYPE)


def test_registration_refuses_unsupported_format_before_release() -> None:
    d = evaluate_registration(doc_type=SALES_REGISTER, declared_format="pdf", source_status="QUARANTINED")
    assert (d.allowed, d.reason) == (False, UNSUPPORTED_FORMAT)


def test_registration_default_denies_without_release_evidence() -> None:
    d = evaluate_registration(
        doc_type=SALES_REGISTER,
        declared_format="csv",
        source_status="QUARANTINED",
        source_released=False,
    )
    assert (d.allowed, d.reason) == (False, SOURCE_NOT_RELEASED)


def test_registration_refuses_rejected_source_even_if_flagged_released() -> None:
    d = evaluate_registration(
        doc_type=SALES_REGISTER,
        declared_format="csv",
        source_status="REJECTED",
        source_released=True,
    )
    assert (d.allowed, d.reason) == (False, SOURCE_NOT_RELEASED)


def test_registration_allows_only_with_supported_type_format_and_release() -> None:
    d = evaluate_registration(
        doc_type=GENERAL_LEDGER,
        declared_format="xlsx",
        source_status="ACCEPTED",
        source_released=True,
    )
    assert (d.allowed, d.reason) == (True, "")


def test_identity_is_stable_and_optional_fields_matter() -> None:
    assert _identity() == _identity()
    assert _identity() != _identity(doc_type=GENERAL_LEDGER)
    assert _identity() != _identity(source_content_sha256="c" * 64)
    assert _identity() != _identity(parser_version="p1")
    assert _identity() == _identity(parser_version=None)


def test_identity_preserves_source_hash_vs_dataset_fingerprint_distinction() -> None:
    # The normalized dataset fingerprint later participates in identity, but the
    # raw source hash is never substituted for it.
    with_fp = registration_identity(
        tenant_id="t1",
        client_id="c1",
        source_intake_id="s1",
        doc_type=SALES_REGISTER,
        declared_format="csv",
        source_content_sha256=SHA,
        dataset_fingerprint=FP,
    )
    assert with_fp != _identity()


def test_eligibility_blocks_on_missing_dataset_fingerprint() -> None:
    out = derive_eligibility(dataset_fingerprint=None, mapping_approved=True, source_released=True)
    assert (out.eligible, out.reason) == (False, MISSING_DATASET_FINGERPRINT)


def test_eligibility_blocks_on_unapproved_mapping() -> None:
    out = derive_eligibility(dataset_fingerprint=FP, mapping_approved=False, source_released=True)
    assert (out.eligible, out.reason) == (False, UNAPPROVED_MAPPING)


def test_eligibility_blocks_on_unreleased_source() -> None:
    out = derive_eligibility(dataset_fingerprint=FP, mapping_approved=True, source_released=False)
    assert (out.eligible, out.reason) == (False, SOURCE_NOT_RELEASED)


def test_eligibility_only_when_fingerprint_mapping_and_release_all_hold() -> None:
    out = derive_eligibility(dataset_fingerprint=FP, mapping_approved=True, source_released=True)
    assert (out.eligible, out.reason) == (True, ELIGIBLE)
