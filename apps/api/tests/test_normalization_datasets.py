"""EP-05A dataset tests: preview, readiness, provenance, drift, JoFotara (synthetic)."""

from datetime import date
from decimal import Decimal

from app.normalization import (
    ConfirmedMapping,
    ExtractedRow,
    ExtractedSheet,
    NormalizationOptions,
    SourceDocument,
    build_profile,
    detect_drift,
    normalize_dataset,
)

SALES_HEADERS = ("Invoice Number", "Invoice Date", "Net Amount", "Tax Amount", "Currency")
SALES_MAP = {
    "invoice_number": "Invoice Number",
    "transaction_date": "Invoice Date",
    "net_amount": "Net Amount",
    "tax_amount": "Tax Amount",
    "currency": "Currency",
}
GL_HEADERS = ("Account No.", "Posting Date", "Debit", "Credit", "Currency", "Description")
GL_MAP = {
    "account_code": "Account No.",
    "transaction_date": "Posting Date",
    "debit_amount": "Debit",
    "credit_amount": "Credit",
    "currency": "Currency",
    "description": "Description",
}
DOC = SourceDocument(doc_id="SYN-DS-1", content_hash="synthetic-hash-ds-1", worksheet="Sales")


def sales_opts(**kwargs: object) -> NormalizationOptions:
    base: dict[str, object] = {
        "doc_type": "sales_register",
        "date_format": "DD/MM/YYYY",
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 12, 31),
    }
    base.update(kwargs)
    return NormalizationOptions(**base)  # type: ignore[arg-type]


def test_synthetic_sales_example_normalizes_ready() -> None:
    sheet = ExtractedSheet(
        headers=SALES_HEADERS,
        rows=(
            ExtractedRow(row_number=2, cells=("INV-0001", "05/01/2026", "1,234.500", "197.520", "JOD")),
            ExtractedRow(row_number=3, cells=("INV-0002", "06/01/2026", "-100.000", "-16.000", "JOD")),
            ExtractedRow(row_number=4, cells=("INV-0003", "07/01/2026", "250.00", "40.00", "USD")),
        ),
    )
    mapping = ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=True, mapping_version="3")
    result = normalize_dataset(DOC, sheet, mapping, sales_opts())
    assert result.readiness == "READY_FOR_CHECKS"
    assert (result.counts.total, result.counts.valid, result.counts.warning, result.counts.failed) == (
        3,
        3,
        0,
        0,
    )
    assert result.preview == result.rows  # <=20 rows: preview is the full set
    by_field = {(t.field, t.currency): t.total for t in result.totals}
    assert by_field[("net_amount", "JOD")] == Decimal("1134.500")
    assert by_field[("tax_amount", "JOD")] == Decimal("181.520")
    assert by_field[("net_amount", "USD")] == Decimal("250.00")
    assert len(result.fingerprint) == 64
    assert set(result.timings_ms) == {"mapping_ms", "normalization_ms", "total_ms"}
    assert all(v >= 0 for v in result.timings_ms.values())


def test_synthetic_gl_example_keeps_sides_separate() -> None:
    gl_doc = SourceDocument(doc_id="SYN-GL-1", content_hash="synthetic-hash-gl-1", worksheet="GL")
    sheet = ExtractedSheet(
        headers=GL_HEADERS,
        rows=(
            ExtractedRow(row_number=2, cells=("000101", "10/01/2026", "500.000", "", "JOD", "Sales cash")),
            ExtractedRow(row_number=3, cells=("000202", "11/01/2026", "", "500.000", "JOD", "Revenue")),
        ),
    )
    mapping = ConfirmedMapping(field_map=dict(GL_MAP), confirmed=True, mapping_version="2")
    result = normalize_dataset(
        gl_doc,
        sheet,
        mapping,
        NormalizationOptions(doc_type="general_ledger", date_format="DD/MM/YYYY"),
    )
    assert result.readiness == "READY_FOR_CHECKS"
    by_field = {(t.field, t.currency): t.total for t in result.totals}
    assert by_field == {
        ("debit_amount", "JOD"): Decimal("500.000"),
        ("credit_amount", "JOD"): Decimal("500.000"),
    }
    codes = [f.canonical for f in result.rows[0].fields]
    assert codes.count("debit_amount") == 1 and codes.count("credit_amount") == 1


def test_preview_caps_at_20_with_reconciling_counts() -> None:
    rows = tuple(
        ExtractedRow(
            row_number=i + 2,
            cells=(f"INV-{i:04d}", "05/01/2026", "10.00", "1.60", "JOD"),
        )
        for i in range(25)
    )
    result = normalize_dataset(
        DOC,
        ExtractedSheet(headers=SALES_HEADERS, rows=rows),
        ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=True),
        sales_opts(),
    )
    assert result.readiness == "READY_FOR_CHECKS"
    assert result.counts.total == 25 and len(result.preview) == 20
    assert result.preview == result.rows[:20]
    c = result.counts
    assert c.valid + c.warning + c.failed == c.total


def test_error_isolation_and_totals_exclude_failures() -> None:
    sheet = ExtractedSheet(
        headers=SALES_HEADERS,
        rows=(
            ExtractedRow(row_number=2, cells=("INV-1", "05/01/2026", "100.00", "16.00", "JOD")),
            ExtractedRow(row_number=3, cells=("INV-2", "05/01/2026", "oops", "16.00", "JOD")),
            ExtractedRow(row_number=4, cells=("INV-3", "05/01/2026", "50.00", "8.00", "JOD")),
        ),
    )
    result = normalize_dataset(
        DOC, sheet, ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=True), sales_opts()
    )
    assert [r.status for r in result.rows] == ["VALID", "FAILED", "VALID"]
    assert result.readiness == "NOT_READY" and result.counts.failed == 1
    by_field = {(t.field, t.currency): t.total for t in result.totals}
    assert by_field[("net_amount", "JOD")] == Decimal("150.00")


def test_every_value_carries_exact_source_provenance() -> None:
    sheet = ExtractedSheet(
        headers=SALES_HEADERS,
        rows=(ExtractedRow(row_number=7, cells=("INV-9", "05/01/2026", "9.99", "1.60", "JOD")),),
    )
    result = normalize_dataset(
        DOC, sheet, ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=True), sales_opts()
    )
    for norm_field in result.rows[0].fields:
        loc = norm_field.location
        assert (loc.doc_id, loc.content_hash, loc.worksheet, loc.row_number) == (
            "SYN-DS-1",
            "synthetic-hash-ds-1",
            "Sales",
            7,
        )
        assert loc.header == SALES_HEADERS[loc.column_index]
        assert norm_field.raw == ("INV-9", "05/01/2026", "9.99", "1.60", "JOD")[loc.column_index]


def test_rerun_reproducible_mapping_change_forks_fingerprint() -> None:
    sheet = ExtractedSheet(
        headers=SALES_HEADERS,
        rows=(ExtractedRow(row_number=2, cells=("INV-1", "05/01/2026", "100.00", "16.00", "JOD")),),
    )
    mapping = ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=True, mapping_version="3")
    first = normalize_dataset(DOC, sheet, mapping, sales_opts())
    again = normalize_dataset(DOC, sheet, mapping, sales_opts())
    assert first.fingerprint == again.fingerprint and first.rows == again.rows
    bumped = ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=True, mapping_version="4")
    assert normalize_dataset(DOC, sheet, bumped, sales_opts()).fingerprint != first.fingerprint
    corrected = ExtractedSheet(
        headers=SALES_HEADERS,
        rows=(ExtractedRow(row_number=2, cells=("INV-1", "05/01/2026", "101.00", "16.00", "JOD")),),
    )
    fixed = normalize_dataset(DOC, corrected, mapping, sales_opts())
    assert fixed.fingerprint != first.fingerprint and first.rows[0] != fixed.rows[0]


def test_drift_reconfirmation_flow() -> None:
    saved = build_profile(
        profile_id="SYN-P1",
        tenant_id="T-SYN",
        client_id="C-SYN",
        doc_type="sales_register",
        headers=SALES_HEADERS,
        mapping=ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=True, mapping_version="3"),
    )
    assert detect_drift(saved, SALES_HEADERS).status == "CURRENT"
    renamed = ("Invoice Number", "Invoice Date", "Net Value", "Tax Amount", "Currency")
    drift = detect_drift(saved, renamed)
    assert drift.status == "DRIFT" and drift.requires_reconfirmation
    reconfirmed = ConfirmedMapping(
        field_map={**SALES_MAP, "net_amount": "Net Value"}, confirmed=True, mapping_version="4"
    )
    assert (
        normalize_dataset(
            DOC,
            ExtractedSheet(
                headers=renamed,
                rows=(ExtractedRow(row_number=2, cells=("INV-1", "05/01/2026", "10.00", "1.60", "JOD")),),
            ),
            reconfirmed,
            sales_opts(),
        ).readiness
        == "READY_FOR_CHECKS"
    )


def test_unprofiled_jofotara_refused_without_invention() -> None:
    jofo_doc = SourceDocument(doc_id="SYN-JOFO-1", content_hash="synthetic-hash-jofo-1")
    sheet = ExtractedSheet(
        headers=("Whatever", "Columns"),
        rows=(ExtractedRow(row_number=2, cells=("x", "y")),),
    )
    result = normalize_dataset(
        jofo_doc,
        sheet,
        ConfirmedMapping(field_map={}, confirmed=True),
        NormalizationOptions(doc_type="jofotara_export"),
    )
    assert result.readiness == "NOT_READY" and result.rows == () and result.preview == ()
    assert any("UNSUPPORTED_PROFILE" in i.code for i in result.blocking_issues)
    assert "no approved" in result.blocking_issues[0].message
    assert (result.counts.total, result.counts.failed) == (0, 0)


def test_inputs_never_mutated() -> None:
    sheet = ExtractedSheet(
        headers=SALES_HEADERS,
        rows=(ExtractedRow(row_number=2, cells=("INV-1", "05/01/2026", "10.00", "1.60", "JOD")),),
    )
    mapping = ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=True, mapping_version="3")
    options = sales_opts()
    snapshot = (sheet, mapping, options)
    normalize_dataset(DOC, sheet, mapping, options)
    assert (sheet, mapping, options) == snapshot


def test_ragged_row_fails_without_realignment() -> None:
    sheet = ExtractedSheet(
        headers=SALES_HEADERS,
        rows=(
            ExtractedRow(row_number=2, cells=("INV-1", "05/01/2026", "10.00")),
            ExtractedRow(row_number=3, cells=("INV-2", "05/01/2026", "20.00", "3.20", "JOD")),
        ),
    )
    result = normalize_dataset(
        DOC, sheet, ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=True), sales_opts()
    )
    assert result.rows[0].status == "FAILED"
    assert any("ROW_SHAPE_MISMATCH" in i.code for i in result.rows[0].row_issues)
    assert result.rows[1].status == "VALID" and result.readiness == "NOT_READY"


def test_unmapped_columns_warned_not_blocking() -> None:
    sheet = ExtractedSheet(
        headers=SALES_HEADERS + ("Notes",),
        rows=(ExtractedRow(row_number=2, cells=("INV-1", "05/01/2026", "10.00", "1.60", "JOD", "hi")),),
    )
    result = normalize_dataset(
        DOC, sheet, ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=True), sales_opts()
    )
    assert result.readiness == "READY_FOR_CHECKS"
    assert any("UNMAPPED_COLUMNS" in i.code for i in result.warnings)


def test_empty_dataset_blocked() -> None:
    result = normalize_dataset(
        DOC,
        ExtractedSheet(headers=SALES_HEADERS, rows=()),
        ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=True),
        sales_opts(),
    )
    assert result.readiness == "NOT_READY"
    assert any("EMPTY_DATASET" in i.code for i in result.blocking_issues)


def test_arabic_end_to_end_with_confirmed_mapping() -> None:
    headers = ("رقم الفاتورة", "تاريخ الفاتورة", "صافي المبلغ", "العملة")
    sheet = ExtractedSheet(
        headers=headers,
        rows=(ExtractedRow(row_number=2, cells=("000077", "05/01/2026", "300.00", "JOD")),),
    )
    mapping = ConfirmedMapping(
        field_map={
            "invoice_number": "رقم الفاتورة",
            "transaction_date": "تاريخ الفاتورة",
            "net_amount": "صافي المبلغ",
            "currency": "العملة",
        },
        confirmed=True,
    )
    result = normalize_dataset(DOC, sheet, mapping, sales_opts())
    assert result.readiness == "READY_FOR_CHECKS"
    by_canonical = {f.canonical: f for f in result.rows[0].fields}
    assert by_canonical["invoice_number"].normalized == "000077"
