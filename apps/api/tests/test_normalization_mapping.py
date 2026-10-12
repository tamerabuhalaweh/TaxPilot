"""EP-05A mapping gate, suggestions, and drift tests (synthetic fixtures)."""

import pytest

from app.normalization import (
    ConfirmedMapping,
    ExtractedRow,
    ExtractedSheet,
    NormalizationOptions,
    SourceDocument,
    build_profile,
    detect_drift,
    fingerprint_headers,
    normalize_dataset,
    suggest_mapping,
    validate_mapping,
)

SALES_HEADERS = ("Invoice Number", "Invoice Date", "Net Amount", "Tax Amount", "Currency")
SALES_MAP = {
    "invoice_number": "Invoice Number",
    "transaction_date": "Invoice Date",
    "net_amount": "Net Amount",
    "tax_amount": "Tax Amount",
    "currency": "Currency",
}


def confirmed(field_map: dict[str, str]) -> ConfirmedMapping:
    return ConfirmedMapping(field_map=field_map, confirmed=True, mapping_version="7")


def opts() -> NormalizationOptions:
    return NormalizationOptions(doc_type="sales_register", date_format="DD/MM/YYYY")


# Suggestions are advisory only (FR-EXT-002).
def test_english_headers_suggest_expected_fields() -> None:
    suggestions = {s.header: s.canonical for s in suggest_mapping(SALES_HEADERS, "sales_register")}
    assert suggestions == {
        "Invoice Number": "invoice_number",
        "Invoice Date": "transaction_date",
        "Net Amount": "net_amount",
        "Tax Amount": "tax_amount",
        "Currency": "currency",
    }


def test_arabic_headers_suggest_expected_fields() -> None:
    headers = ("رقم الفاتورة", "تاريخ الفاتورة", "صافي المبلغ", "العملة")
    suggestions = {s.header: s.canonical for s in suggest_mapping(headers, "sales_register")}
    assert suggestions == {
        "رقم الفاتورة": "invoice_number",
        "تاريخ الفاتورة": "transaction_date",
        "صافي المبلغ": "net_amount",
        "العملة": "currency",
    }


def test_unknown_headers_and_types_suggest_nothing() -> None:
    suggestions = suggest_mapping(("Mystery Column", "رقم غير معروف"), "sales_register")
    assert all(s.canonical is None for s in suggestions)
    assert all(s.canonical is None for s in suggest_mapping(SALES_HEADERS, "nope_type"))


def test_suggestions_reject_non_text_headers() -> None:
    with pytest.raises(TypeError):
        suggest_mapping(("Invoice Number", 42), "sales_register")  # type: ignore[arg-type]


def test_perfect_suggestions_still_require_confirmation() -> None:
    doc = SourceDocument(doc_id="SYN-1", content_hash="syn-1")
    sheet = ExtractedSheet(
        headers=SALES_HEADERS,
        rows=(ExtractedRow(row_number=2, cells=("INV-1", "01/02/2026", "100.00", "16.00", "JOD")),),
    )
    unconfirmed = ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=False, mapping_version="7")
    result = normalize_dataset(doc, sheet, unconfirmed, opts())
    assert result.readiness == "NOT_READY"
    assert any("MAPPING_UNCONFIRMED_MAPPING" in i.code for i in result.blocking_issues)
    assert result.rows == ()


# Duplicate / conflicting / missing mappings fail closed.
def test_duplicate_headers_rejected() -> None:
    report = validate_mapping(
        ("Invoice Number", "Invoice Number", "Net Amount"),
        confirmed({"invoice_number": "Invoice Number", "net_amount": "Net Amount"}),
        "sales_register",
    )
    assert not report.ok
    assert any(i.code == "DUPLICATE_HEADER" for i in report.issues)


def test_case_variant_duplicates_rejected() -> None:
    report = validate_mapping(
        ("Debit", "debit", "Account No."),
        confirmed({"account_code": "Account No.", "debit_amount": "Debit"}),
        "general_ledger",
    )
    assert not report.ok
    assert any(i.code == "DUPLICATE_HEADER" for i in report.issues)


def test_conflicting_mapping_rejected() -> None:
    report = validate_mapping(
        ("Amount",),
        confirmed({"invoice_number": "Amount", "net_amount": "Amount"}),
        "sales_register",
    )
    assert not report.ok
    assert any(i.code == "CONFLICTING_MAPPING" for i in report.issues)


def test_missing_required_field_rejected() -> None:
    report = validate_mapping(
        ("Invoice Number", "Invoice Date"),
        confirmed({"invoice_number": "Invoice Number", "transaction_date": "Invoice Date"}),
        "sales_register",
    )
    assert not report.ok
    assert any(i.code == "MISSING_REQUIRED_FIELD" for i in report.issues)


def test_missing_source_column_rejected() -> None:
    report = validate_mapping(
        ("Invoice Number",),
        confirmed({"invoice_number": "Renamed Away"}),
        "sales_register",
    )
    assert not report.ok
    assert any(i.code == "MISSING_SOURCE_COLUMN" for i in report.issues)


def test_unknown_field_rejected() -> None:
    field_map = dict(SALES_MAP)
    field_map["vat_rate"] = "Tax Amount"
    report = validate_mapping(SALES_HEADERS, confirmed(field_map), "sales_register")
    assert not report.ok
    assert any(i.code == "UNKNOWN_FIELD" for i in report.issues)


def test_gl_requires_an_amount_mapping() -> None:
    report = validate_mapping(
        ("Account No.", "Posting Date"),
        confirmed({"account_code": "Account No.", "transaction_date": "Posting Date"}),
        "general_ledger",
    )
    assert not report.ok
    assert any(i.code == "MISSING_REQUIRED_FIELD" for i in report.issues)


def test_unknown_document_type_rejected() -> None:
    report = validate_mapping(("A",), confirmed({}), "bank_statement")
    assert not report.ok
    assert report.issues[0].code == "UNKNOWN_DOCUMENT_TYPE"


def test_valid_mapping_returns_column_indexes() -> None:
    report = validate_mapping(SALES_HEADERS, confirmed(dict(SALES_MAP)), "sales_register")
    assert report.ok and report.issues == ()
    assert report.column_index == {
        "invoice_number": 0,
        "transaction_date": 1,
        "net_amount": 2,
        "tax_amount": 3,
        "currency": 4,
    }
    assert len(report.header_fingerprint) == 64


# Drift and versioned reuse (FR-EXT-010; persistence excluded).
def test_header_fingerprint_stable_and_sensitive() -> None:
    assert fingerprint_headers(SALES_HEADERS) == fingerprint_headers(tuple(SALES_HEADERS))
    assert fingerprint_headers(SALES_HEADERS) != fingerprint_headers(SALES_HEADERS + ("Extra",))


def test_no_drift_on_identical_headers() -> None:
    saved = build_profile(
        profile_id="P1",
        tenant_id="T1",
        client_id="C1",
        doc_type="sales_register",
        headers=SALES_HEADERS,
        mapping=confirmed(dict(SALES_MAP)),
    )
    assert saved.mapping_version == "7"
    drift = detect_drift(saved, SALES_HEADERS)
    assert drift.status == "CURRENT" and not drift.requires_reconfirmation


def test_renamed_header_is_drift_requiring_reconfirmation() -> None:
    saved = build_profile(
        profile_id="P1",
        tenant_id="T1",
        client_id="C1",
        doc_type="sales_register",
        headers=SALES_HEADERS,
        mapping=confirmed(dict(SALES_MAP)),
    )
    renamed = ("Invoice Number", "Invoice Date", "Net Value", "Tax Amount", "Currency")
    drift = detect_drift(saved, renamed)
    assert drift.status == "DRIFT" and drift.requires_reconfirmation
    assert drift.added and drift.removed


def test_invalid_mapping_cannot_be_versioned() -> None:
    with pytest.raises(ValueError, match="invalid mapping"):
        build_profile(
            profile_id="P1",
            tenant_id="T1",
            client_id="C1",
            doc_type="sales_register",
            headers=("Invoice Number",),
            mapping=confirmed({"invoice_number": "Renamed Away"}),
        )
