"""EP-05A field normalization tests: dates, money, identifiers, GL (synthetic)."""

from datetime import date
from decimal import Decimal

from app.normalization import (
    ConfirmedMapping,
    DatasetResult,
    ExtractedRow,
    ExtractedSheet,
    NormalizationOptions,
    NormalizedField,
    SourceDocument,
    normalize_dataset,
)

SALES_HEADERS = ("Invoice Number", "Invoice Date", "Net Amount", "Currency")
SALES_MAP = {
    "invoice_number": "Invoice Number",
    "transaction_date": "Invoice Date",
    "net_amount": "Net Amount",
    "currency": "Currency",
}
GL_HEADERS = ("Account No.", "Posting Date", "Debit", "Credit", "Currency")
GL_MAP = {
    "account_code": "Account No.",
    "transaction_date": "Posting Date",
    "debit_amount": "Debit",
    "credit_amount": "Credit",
    "currency": "Currency",
}


def sales_opts(**kwargs: object) -> NormalizationOptions:
    base: dict[str, object] = {"doc_type": "sales_register", "date_format": "DD/MM/YYYY"}
    base.update(kwargs)
    return NormalizationOptions(**base)  # type: ignore[arg-type]


def gl_opts(**kwargs: object) -> NormalizationOptions:
    base: dict[str, object] = {"doc_type": "general_ledger", "date_format": "DD/MM/YYYY"}
    base.update(kwargs)
    return NormalizationOptions(**base)  # type: ignore[arg-type]


def sales_sheet(*rows: tuple[str, ...]) -> ExtractedSheet:
    return ExtractedSheet(
        headers=SALES_HEADERS,
        rows=tuple(ExtractedRow(row_number=i + 2, cells=r) for i, r in enumerate(rows)),
    )


def gl_sheet(*rows: tuple[str, ...]) -> ExtractedSheet:
    return ExtractedSheet(
        headers=GL_HEADERS,
        rows=tuple(ExtractedRow(row_number=i + 2, cells=r) for i, r in enumerate(rows)),
    )


DOC = SourceDocument(doc_id="SYN-FIELDS-1", content_hash="syn-fields-1", worksheet="Sheet1")
MAPPING = ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=True, mapping_version="1")
GL_MAPPING = ConfirmedMapping(field_map=dict(GL_MAP), confirmed=True, mapping_version="1")


def field_of(result: DatasetResult, row: int, canonical: str) -> NormalizedField:
    fields = {f.canonical: f for f in result.rows[row].fields}
    return fields[canonical]


# Dates: ambiguous blocked, DMY vs MDY distinguished, invalid rejected.
def test_ambiguous_date_without_format_blocks() -> None:
    result = normalize_dataset(
        DOC, sales_sheet(("INV-1", "01/02/2026", "100.00", "JOD")), MAPPING, sales_opts(date_format=None)
    )
    assert result.readiness == "NOT_READY"
    issues = field_of(result, 0, "transaction_date").issues
    assert any("AMBIGUOUS_DATE_FORMAT" in i.code for i in issues)
    assert field_of(result, 0, "transaction_date").normalized is None


def test_dmy_vs_mdy_distinguished() -> None:
    dmy = normalize_dataset(DOC, sales_sheet(("INV-1", "01/02/2026", "100.00", "JOD")), MAPPING, sales_opts())
    mdy = normalize_dataset(
        DOC,
        sales_sheet(("INV-1", "01/02/2026", "100.00", "JOD")),
        MAPPING,
        sales_opts(date_format="MM/DD/YYYY"),
    )
    assert dmy.rows[0].status != "FAILED"
    assert mdy.rows[0].status != "FAILED"
    dmy_date = field_of(dmy, 0, "transaction_date").normalized
    mdy_date = field_of(mdy, 0, "transaction_date").normalized
    assert dmy_date == date(2026, 2, 1) and mdy_date == date(2026, 1, 2)
    assert dmy_date != mdy_date


def test_leap_and_invalid_calendar_dates() -> None:
    ok = normalize_dataset(DOC, sales_sheet(("INV-1", "29/02/2024", "1.00", "JOD")), MAPPING, sales_opts())
    assert field_of(ok, 0, "transaction_date").normalized == date(2024, 2, 29)
    for bad in ("29/02/2025", "32/01/2026", "13/13/2026", "01/02/26", "2026-02-01"):
        result = normalize_dataset(DOC, sales_sheet(("INV-1", bad, "1.00", "JOD")), MAPPING, sales_opts())
        issues = field_of(result, 0, "transaction_date").issues
        assert any("INVALID_DATE" in i.code for i in issues), bad


def test_unknown_date_format_code_blocked() -> None:
    result = normalize_dataset(
        DOC,
        sales_sheet(("INV-1", "01/02/2026", "1.00", "JOD")),
        MAPPING,
        sales_opts(date_format="FEB/2026??"),
    )
    assert result.readiness == "NOT_READY"
    assert any("INVALID_DATE_PROFILE" in i.code for i in result.blocking_issues)


def test_out_of_period_flagged_not_dropped() -> None:
    result = normalize_dataset(
        DOC,
        sales_sheet(("INV-1", "15/06/2025", "10.00", "JOD")),
        MAPPING,
        sales_opts(period_start=date(2026, 1, 1), period_end=date(2026, 12, 31)),
    )
    row = result.rows[0]
    assert any("OUT_OF_PERIOD" in i.code for f in row.fields for i in f.issues)
    assert field_of(result, 0, "transaction_date").normalized == date(2025, 6, 15)
    assert result.counts.warning == 1 and result.readiness == "READY_FOR_CHECKS"


# Money: exact under hostile precision, segregated, blank/zero/invalid distinct.
def test_exact_long_amount_under_low_precision() -> None:
    import decimal

    long_value = "12345678901234567890123456789.12345"
    result = normalize_dataset(
        DOC,
        ExtractedSheet(
            headers=("Net Amount", "Invoice Number", "Invoice Date", "Currency"),
            rows=(ExtractedRow(row_number=2, cells=(long_value, "INV-9", "01/02/2026", "JOD")),),
        ),
        ConfirmedMapping(
            field_map={
                "invoice_number": "Invoice Number",
                "transaction_date": "Invoice Date",
                "net_amount": "Net Amount",
                "currency": "Currency",
            },
            confirmed=True,
        ),
        NormalizationOptions(
            doc_type="sales_register",
            decimal_separator=".",
            grouping_separator=None,
            date_format="DD/MM/YYYY",
        ),
    )
    with decimal.localcontext() as ctx:
        ctx.prec = 10
        assert result.readiness == "READY_FOR_CHECKS"
    assert field_of(result, 0, "net_amount").normalized == Decimal(long_value)


def test_mixed_currencies_segregated_never_combined() -> None:
    result = normalize_dataset(
        DOC,
        sales_sheet(
            ("INV-1", "01/02/2026", "100.00", "JOD"),
            ("INV-2", "02/02/2026", "50.00", "USD"),
        ),
        MAPPING,
        sales_opts(),
    )
    assert result.readiness == "READY_FOR_CHECKS"
    totals = {(t.field, t.currency): t.total for t in result.totals}
    assert totals == {("net_amount", "JOD"): Decimal("100.00"), ("net_amount", "USD"): Decimal("50.00")}


def test_blank_zero_invalid_amounts_distinct() -> None:
    result = normalize_dataset(
        DOC,
        sales_sheet(
            ("INV-1", "01/02/2026", "0.00", "JOD"),
            ("INV-2", "01/02/2026", "", "JOD"),
            ("INV-3", "01/02/2026", "N/A", "JOD"),
        ),
        MAPPING,
        sales_opts(),
    )
    zero = field_of(result, 0, "net_amount")
    blank = field_of(result, 1, "net_amount")
    invalid = field_of(result, 2, "net_amount")
    assert zero.normalized == Decimal("0.00") and zero.issues == ()
    assert any("MISSING_AMOUNT" in i.code for i in blank.issues) and blank.normalized is None
    assert any("INVALID_AMOUNT" in i.code for i in invalid.issues) and invalid.normalized is None
    assert result.counts.failed == 2 and result.readiness == "NOT_READY"


def test_no_default_currency_assumption() -> None:
    no_currency_map = ConfirmedMapping(
        field_map={k: v for k, v in SALES_MAP.items() if k != "currency"},
        confirmed=True,
    )
    sheet = ExtractedSheet(
        headers=("Invoice Number", "Invoice Date", "Net Amount"),
        rows=(ExtractedRow(row_number=2, cells=("INV-1", "01/02/2026", "100.00")),),
    )
    blocked = normalize_dataset(DOC, sheet, no_currency_map, sales_opts(default_currency=None))
    assert blocked.readiness == "NOT_READY"
    assert any("MISSING_CURRENCY_SOURCE" in i.code for i in blocked.blocking_issues)
    approved = normalize_dataset(DOC, sheet, no_currency_map, sales_opts(default_currency="USD"))
    assert approved.readiness == "READY_FOR_CHECKS"
    assert field_of(approved, 0, "net_amount").currency == "USD"


def test_malformed_currency_blocked() -> None:
    result = normalize_dataset(
        DOC, sales_sheet(("INV-1", "01/02/2026", "10.00", "US")), MAPPING, sales_opts()
    )
    assert result.readiness == "NOT_READY"
    assert any("INVALID_CURRENCY" in i.code for f in result.rows[0].fields for i in f.issues)


# Identifiers stay verbatim strings; GL debit/credit independent.
def test_leading_zero_identifiers_preserved() -> None:
    result = normalize_dataset(
        DOC, sales_sheet(("000123", "01/02/2026", "5.00", "JOD")), MAPPING, sales_opts()
    )
    value = field_of(result, 0, "invoice_number")
    assert value.normalized == "000123" and isinstance(value.normalized, str)


def test_gl_debit_credit_separate_and_negatives_preserved() -> None:
    result = normalize_dataset(
        DOC,
        gl_sheet(
            ("000123", "01/02/2026", "250.00", "", "JOD"),
            ("000124", "02/02/2026", "", "75.50", "JOD"),
            ("000125", "03/02/2026", "-50.00", "", "JOD"),
            ("000126", "04/02/2026", "20.00", "20.00", "JOD"),
        ),
        GL_MAPPING,
        gl_opts(),
    )
    assert result.readiness == "READY_FOR_CHECKS"
    rows = {r.row_number: r for r in result.rows}
    assert field_of(result, 0, "debit_amount").normalized == Decimal("250.00")
    assert field_of(result, 1, "credit_amount").normalized == Decimal("75.50")
    assert field_of(result, 2, "debit_amount").normalized == Decimal("-50.00")
    both = rows[5]
    assert field_of(result, 3, "debit_amount").normalized == Decimal("20.00")
    assert field_of(result, 3, "credit_amount").normalized == Decimal("20.00")
    assert both.status == "VALID"  # both sides kept, never netted
    totals = {(t.field, t.currency): t.total for t in result.totals}
    assert totals[("debit_amount", "JOD")] == Decimal("220.00")
    assert totals[("credit_amount", "JOD")] == Decimal("95.50")


def test_gl_empty_entry_warns_without_failing() -> None:
    result = normalize_dataset(DOC, gl_sheet(("000127", "05/02/2026", "", "", "JOD")), GL_MAPPING, gl_opts())
    assert result.rows[0].status == "WARNING"
    assert any("EMPTY_GL_ENTRY" in i.code for i in result.rows[0].row_issues)
    assert result.readiness == "READY_FOR_CHECKS"
