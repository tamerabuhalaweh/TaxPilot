"""REC-JOFO-01 unit contracts: default-deny JoFotara import profiles.

No authorized samples or documented official layout exist (blocker B-01 OPEN,
decision DEC-10 OPEN), so the shipped registry is empty and every real layout is
refused. The only "approved" profile used here is an explicitly **synthetic test
double** (``issuing_source = "synthetic-test-only"``) that exists to exercise the
recognition/validation machinery — it is NOT a JoFotara layout and must never be
shipped or represented as official.
"""

import pytest

from app.jofotara import (
    AMBIGUOUS_PROFILE_MATCH,
    AUTHORITY_AUTHORIZED_SAMPLE,
    DEFAULT_JOFOTARA_REGISTRY,
    DUPLICATE_HEADER,
    EMPTY_HEADERS,
    EXTERNAL_REFERENCE,
    FORMULA_CELL,
    HEADER_DRIFT,
    MALFORMED_NUMBER,
    MISSING_COLUMN,
    MISSING_CURRENCY,
    MISSING_REQUIRED_COLUMN,
    MISSING_VALUE,
    NO_APPROVED_PROFILE,
    NOT_RECOGNIZED,
    PROFILE_APPROVED,
    PROFILE_DRAFT,
    PROFILE_NOT_APPROVED,
    RECOGNIZED,
    UNKNOWN_CURRENCY,
    UNSUPPORTED_WORKSHEET,
    JoFotaraContractError,
    JoFotaraProfile,
    JoFotaraProfileRegistry,
    JoFotaraRowProvenance,
    MoneySemantics,
    ProfileProvenance,
    build_jofotara_invoice,
    normalize_currency,
    normalize_identifier,
    parse_money,
    recognize_jofotara_profile,
    validate_jofotara_profile,
)
from app.normalization.mapping import fingerprint_headers

WORK_SHEET = "SyntheticSheet"
HEADERS = (
    "SyntheticInvoiceNo",
    "SyntheticDate",
    "SyntheticNet",
    "SyntheticTax",
    "SyntheticGross",
    "SyntheticCcy",
)
COLUMN_MAP = {
    "invoice_number": "SyntheticInvoiceNo",
    "issue_date": "SyntheticDate",
    "net_amount": "SyntheticNet",
    "tax_amount": "SyntheticTax",
    "gross_amount": "SyntheticGross",
    "currency": "SyntheticCcy",
}
MONEY = MoneySemantics(decimal_separator=".", grouping_separator=",")


def _provenance() -> ProfileProvenance:
    return ProfileProvenance(
        issuing_source="synthetic-test-only",
        authority_type=AUTHORITY_AUTHORIZED_SAMPLE,
        extracted_at="synthetic-test-only",
        redistribution_permission="synthetic-test-only",
    )


def _profile(**overrides: object) -> JoFotaraProfile:
    base: dict = {
        "profile_id": "synthetic-test-profile",
        "profile_version": "0",
        "worksheet_names": (WORK_SHEET,),
        "header_fingerprint": fingerprint_headers(HEADERS),
        "column_map": COLUMN_MAP,
        "required_fields": ("invoice_number", "net_amount"),
        "money": MONEY,
        "date_format": "YYYY-MM-DD",
        "status": PROFILE_APPROVED,
        "approved_by": "synthetic-test",
        "approved_at": "synthetic-test",
        "provenance": _provenance(),
    }
    base.update(overrides)
    return JoFotaraProfile(**base)


def _registry(*profiles: JoFotaraProfile) -> JoFotaraProfileRegistry:
    return JoFotaraProfileRegistry(tuple(profiles))


# -- master default-deny (no authorized samples exist) ---------------------------


def test_shipped_registry_is_empty() -> None:
    assert DEFAULT_JOFOTARA_REGISTRY.approved_profiles() == ()


def test_any_real_layout_is_refused_with_empty_registry() -> None:
    outcome = recognize_jofotara_profile(worksheet=WORK_SHEET, headers=HEADERS)
    assert (outcome.recognized, outcome.reason) == (False, NO_APPROVED_PROFILE)
    assert outcome.profile is None


def test_empty_headers_refused() -> None:
    outcome = recognize_jofotara_profile(worksheet=WORK_SHEET, headers=())
    assert (outcome.recognized, outcome.reason) == (False, EMPTY_HEADERS)


def test_duplicate_headers_refused() -> None:
    dupes = ("SyntheticInvoiceNo", "SyntheticInvoiceNo", "SyntheticNet")
    outcome = recognize_jofotara_profile(worksheet=WORK_SHEET, headers=dupes)
    assert (outcome.recognized, outcome.reason) == (False, DUPLICATE_HEADER)


def test_build_invoice_refused_without_recognition() -> None:
    with pytest.raises(JoFotaraContractError) as exc:
        build_jofotara_invoice(
            recognition=recognize_jofotara_profile(worksheet=WORK_SHEET, headers=HEADERS),
            issuer="Issuer",
            number="INV-1",
            currency="JOD",
            net_amount=None,
            tax_amount=None,
            gross_amount=None,
        )
    assert exc.value.code == NOT_RECOGNIZED


# -- recognition mechanics (synthetic test double) -------------------------------


def test_exact_layout_recognized() -> None:
    outcome = recognize_jofotara_profile(
        worksheet=WORK_SHEET, headers=HEADERS, registry=_registry(_profile())
    )
    assert outcome.recognized is True
    assert outcome.reason == RECOGNIZED
    assert outcome.profile is not None


def test_unsupported_worksheet_refused() -> None:
    outcome = recognize_jofotara_profile(
        worksheet="SomeOtherSheet", headers=HEADERS, registry=_registry(_profile())
    )
    assert (outcome.recognized, outcome.reason) == (False, UNSUPPORTED_WORKSHEET)


def test_altered_headers_refused_as_drift() -> None:
    altered = tuple(reversed(HEADERS))
    outcome = recognize_jofotara_profile(
        worksheet=WORK_SHEET, headers=altered, registry=_registry(_profile())
    )
    assert (outcome.recognized, outcome.reason) == (False, HEADER_DRIFT)


def test_draft_only_profile_refused_as_not_approved() -> None:
    draft = _profile(
        profile_id="synthetic-draft",
        status=PROFILE_DRAFT,
        approved_by="",
        approved_at="",
        provenance=None,
        header_fingerprint=fingerprint_headers(HEADERS + ("Extra",)),
    )
    # An approved profile claims the worksheet but a different fingerprint; the
    # matching draft must surface as actionable "not approved" guidance.
    approved_other = _profile(profile_id="synthetic-approved-other")
    outcome = recognize_jofotara_profile(
        worksheet=WORK_SHEET, headers=HEADERS + ("Extra",), registry=_registry(approved_other, draft)
    )
    assert (outcome.recognized, outcome.reason) == (False, PROFILE_NOT_APPROVED)


def test_ambiguous_profiles_refused() -> None:
    a = _profile(profile_id="p-a")
    b = _profile(profile_id="p-b")
    outcome = recognize_jofotara_profile(worksheet=WORK_SHEET, headers=HEADERS, registry=_registry(a, b))
    assert (outcome.recognized, outcome.reason) == (False, AMBIGUOUS_PROFILE_MATCH)


def test_registry_rejects_duplicate_identity() -> None:
    with pytest.raises(ValueError):
        _registry(_profile(), _profile())


# -- profile manifest invariants -------------------------------------------------


def test_approved_profile_requires_provenance() -> None:
    with pytest.raises(ValueError):
        _profile(provenance=None)


def test_approved_profile_requires_approver() -> None:
    with pytest.raises(ValueError):
        _profile(approved_by="")


def test_unknown_canonical_field_rejected() -> None:
    with pytest.raises(ValueError):
        _profile(column_map={**COLUMN_MAP, "made_up_field": "SyntheticNet"})


def test_required_field_must_be_in_column_map() -> None:
    with pytest.raises(ValueError):
        _profile(required_fields=("reference_number",))


def test_ambiguous_money_separators_rejected() -> None:
    with pytest.raises(ValueError):
        MoneySemantics(decimal_separator=",", grouping_separator=",")


# -- strict column validation ----------------------------------------------------


def test_validation_detects_missing_column() -> None:
    profile = _profile(column_map={**COLUMN_MAP, "issuer": "SyntheticIssuer"})
    result = validate_jofotara_profile(profile, HEADERS)
    assert result.ok is False
    assert MISSING_COLUMN in tuple(i.code for i in result.issues)


def test_validation_detects_required_column() -> None:
    profile = _profile(
        required_fields=("gross_amount",),
        column_map={"invoice_number": "SyntheticInvoiceNo", "gross_amount": "NoSuchColumn"},
    )
    result = validate_jofotara_profile(profile, HEADERS)
    assert result.ok is False
    codes = tuple(i.code for i in result.issues)
    assert MISSING_COLUMN in codes
    assert MISSING_REQUIRED_COLUMN in codes


def test_validation_detects_duplicate_headers() -> None:
    profile = _profile(header_fingerprint=fingerprint_headers(("A", "A")))
    result = validate_jofotara_profile(profile, ("A", "A"))
    assert result.ok is False
    assert DUPLICATE_HEADER in tuple(i.code for i in result.issues)


# -- exact value handling --------------------------------------------------------


def test_parse_money_exact_with_declared_separators() -> None:
    assert str(parse_money("1,234.56", MONEY)) == "1234.56"
    assert str(parse_money("1234.56", MONEY)) == "1234.56"
    assert str(parse_money("-0.01", MONEY)) == "-0.01"


def test_parse_money_rejects_blank_never_zero() -> None:
    with pytest.raises(JoFotaraContractError) as exc:
        parse_money("   ", MONEY)
    assert exc.value.code == MISSING_VALUE


def test_parse_money_rejects_formula_and_external_reference() -> None:
    with pytest.raises(JoFotaraContractError) as exc:
        parse_money("=SUM(A1:A2)", MONEY)
    assert exc.value.code == FORMULA_CELL
    with pytest.raises(JoFotaraContractError) as exc:
        parse_money("[Book1.xlsx]Sheet1!A1", MONEY)
    assert exc.value.code == EXTERNAL_REFERENCE


def test_parse_money_rejects_malformed_and_non_text() -> None:
    with pytest.raises(JoFotaraContractError) as exc:
        parse_money("12abc", MONEY)
    assert exc.value.code == MALFORMED_NUMBER
    with pytest.raises(JoFotaraContractError) as exc:
        parse_money("1.2.3", MONEY)
    assert exc.value.code == MALFORMED_NUMBER
    with pytest.raises(TypeError):
        parse_money(1234.56, MONEY)  # no float path


def test_identifier_preserves_leading_zeros() -> None:
    assert normalize_identifier("000123") == "000123"
    with pytest.raises(JoFotaraContractError) as exc:
        normalize_identifier("  ")
    assert exc.value.code == MISSING_VALUE


def test_currency_explicit_never_assumed() -> None:
    assert normalize_currency("jod") == "JOD"
    with pytest.raises(JoFotaraContractError) as exc:
        normalize_currency("")
    assert exc.value.code == MISSING_CURRENCY
    with pytest.raises(JoFotaraContractError) as exc:
        normalize_currency("JODD")
    assert exc.value.code == UNKNOWN_CURRENCY


# -- invoice construction (approved path; missing money stays None) --------------


def test_invoice_built_only_from_approved_profile() -> None:
    recognition = recognize_jofotara_profile(
        worksheet=WORK_SHEET, headers=HEADERS, registry=_registry(_profile())
    )
    provenance = JoFotaraRowProvenance(dataset_id="ds-1", worksheet=WORK_SHEET, row_number=2)
    invoice = build_jofotara_invoice(
        recognition=recognition,
        issuer="Example Trading LLC",
        number="000123",
        currency="jod",
        net_amount=parse_money("100.000", MONEY),
        tax_amount=None,
        gross_amount=None,
        reference_number="CN-0001",
        is_credit_note=True,
        provenance=provenance,
    )
    assert invoice.number == "000123"
    assert invoice.currency == "JOD"
    assert invoice.tax_amount is None  # missing, never zero
    assert invoice.is_credit_note is True
    assert invoice.provenance == provenance
