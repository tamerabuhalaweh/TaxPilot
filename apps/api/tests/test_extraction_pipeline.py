"""EP-04A end-to-end: bytes -> extraction -> mapping -> normalization (synthetic).

Proves CSV/XLSX -> ExtractedSheet -> approved mapping -> exact Decimal totals,
and that ambiguity/failure anywhere in the chain stays NOT_READY.
"""

import hashlib
import io
from decimal import Decimal

import pytest
from openpyxl import Workbook  # type: ignore[import-untyped]

from app.extraction import (
    CsvSettings,
    ExtractionError,
    XlsxSettings,
    extract_bytes,
    extract_stream,
)
from app.normalization import (
    ConfirmedMapping,
    NormalizationOptions,
    normalize_dataset,
)

SALES_MAP = {
    "invoice_number": "Invoice Number",
    "transaction_date": "Invoice Date",
    "net_amount": "Net Amount",
    "currency": "Currency",
}


def sales_options(**kwargs: object) -> NormalizationOptions:
    base: dict[str, object] = {
        "doc_type": "sales_register",
        "decimal_separator": ".",
        "grouping_separator": ",",
        "date_format": "DD/MM/YYYY",
    }
    base.update(kwargs)
    return NormalizationOptions(**base)  # type: ignore[arg-type]


def confirmed() -> ConfirmedMapping:
    return ConfirmedMapping(field_map=dict(SALES_MAP), confirmed=True, mapping_version="e2e-1")


def sales_xlsx_bytes(rows: list[list[str]], sheet: str = "Sales") -> bytes:
    workbook = Workbook()
    active = workbook.active
    active.title = sheet
    for row in rows:
        active.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


SALES_ROWS = [
    ["Invoice Number", "Invoice Date", "Net Amount", "Currency"],
    ["INV-0001", "05/01/2026", "1,234.500", "JOD"],
    ["000123", "06/01/2026", "-100.000", "JOD"],
    ["INV-0003", "07/01/2026", "250.00", "USD"],
]


def test_csv_to_exact_segregated_totals() -> None:
    csv_text = (
        "Invoice Number,Invoice Date,Net Amount,Currency\n"
        'INV-0001,05/01/2026,"1,234.500",JOD\n'
        "000123,06/01/2026,-100.000,JOD\n"
        "INV-0003,07/01/2026,250.00,USD\n"
    )
    data = csv_text.encode("utf-8")
    extracted = extract_bytes(
        data, declared_format="csv", doc_id="SYN-E2E-CSV", csv=CsvSettings(delimiter=",")
    )
    assert extracted.doc.content_hash == hashlib.sha256(data).hexdigest()
    result = normalize_dataset(extracted.doc, extracted.sheet, confirmed(), sales_options())
    assert result.readiness == "READY_FOR_CHECKS"
    assert [r.row_number for r in result.rows] == [2, 3, 4]  # CSV line provenance
    by_field = {(t.field, t.currency): t.total for t in result.totals}
    assert by_field[("net_amount", "JOD")] == Decimal("1134.500")
    assert by_field[("net_amount", "USD")] == Decimal("250.00")
    assert (result.eligible_rows, result.excluded_rows) == (3, 0)


def test_xlsx_arabic_to_ready_with_leading_zeros() -> None:
    rows = [
        ["رقم الفاتورة", "تاريخ الفاتورة", "صافي المبلغ", "العملة"],
        ["000077", "05/01/2026", "300.00", "JOD"],
        ["000078", "06/01/2026", "450.250", "JOD"],
    ]
    data = sales_xlsx_bytes(rows, sheet="المبيعات")
    extracted = extract_bytes(
        data, declared_format="xlsx", doc_id="SYN-E2E-AR", xlsx=XlsxSettings(sheet_name="المبيعات")
    )
    mapping = ConfirmedMapping(
        field_map={
            "invoice_number": "رقم الفاتورة",
            "transaction_date": "تاريخ الفاتورة",
            "net_amount": "صافي المبلغ",
            "currency": "العملة",
        },
        confirmed=True,
        mapping_version="e2e-ar-1",
    )
    result = normalize_dataset(extracted.doc, extracted.sheet, mapping, sales_options())
    assert result.readiness == "READY_FOR_CHECKS"
    identifiers = [f for f in result.rows[0].fields if f.canonical == "invoice_number"]
    assert identifiers[0].normalized == "000077"
    by_field = {(t.field, t.currency): t.total for t in result.totals}
    assert by_field[("net_amount", "JOD")] == Decimal("750.250")


def test_xlsx_numeric_cells_block_pipeline_by_default() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    for row in (["A", "B"], ["x", 1234.5]):
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    with pytest.raises(ExtractionError) as exc:
        extract_bytes(
            buffer.getvalue(),
            declared_format="xlsx",
            doc_id="D",
            xlsx=XlsxSettings(sheet_name="Sales"),
        )
    assert exc.value.code == "TYPED_CELLS"


def test_ambiguous_date_stays_not_ready_end_to_end() -> None:
    data = b"Invoice Number,Invoice Date,Net Amount,Currency\nINV-1,01/02/2026,10.00,JOD\n"
    extracted = extract_bytes(data, declared_format="csv", doc_id="D", csv=CsvSettings(delimiter=","))
    result = normalize_dataset(extracted.doc, extracted.sheet, confirmed(), sales_options(date_format=None))
    assert result.readiness == "NOT_READY"
    assert any("AMBIGUOUS_DATE_FORMAT" in i.code for f in result.rows[0].fields for i in f.issues)


def test_duplicate_headers_rejected_at_mapping_gate() -> None:
    data = b"Invoice Number,Invoice Number,Net Amount,Currency\nINV-1,INV-1,10.00,JOD\n"
    extracted = extract_bytes(data, declared_format="csv", doc_id="D", csv=CsvSettings(delimiter=","))
    assert extracted.sheet.headers == ("Invoice Number", "Invoice Number", "Net Amount", "Currency")
    result = normalize_dataset(extracted.doc, extracted.sheet, confirmed(), sales_options())
    assert result.readiness == "NOT_READY"
    assert any("MAPPING_DUPLICATE_HEADER" in i.code for i in result.blocking_issues)


def test_jofotara_bytes_stay_unsupported_without_invention() -> None:
    data = b"Some,Headers\n1,2\n"
    extracted = extract_bytes(data, declared_format="csv", doc_id="SYN-JOFO", csv=CsvSettings(delimiter=","))
    result = normalize_dataset(
        extracted.doc,
        extracted.sheet,
        ConfirmedMapping(field_map={}, confirmed=True),
        NormalizationOptions(doc_type="jofotara_export", decimal_separator=".", grouping_separator=","),
    )
    assert result.readiness == "NOT_READY"
    assert any("UNSUPPORTED_PROFILE" in i.code for i in result.blocking_issues)


def test_stream_bytes_parity_and_hash_stability() -> None:
    data = sales_xlsx_bytes(SALES_ROWS)
    via_bytes = extract_bytes(data, declared_format="xlsx", doc_id="D", xlsx=XlsxSettings(sheet_name="Sales"))
    via_stream = extract_stream(
        io.BytesIO(data), declared_format="xlsx", doc_id="D", xlsx=XlsxSettings(sheet_name="Sales")
    )
    assert via_stream.sheet == via_bytes.sheet
    assert via_stream.doc.content_hash == via_bytes.doc.content_hash
    first = normalize_dataset(via_bytes.doc, via_bytes.sheet, confirmed(), sales_options())
    second = normalize_dataset(via_stream.doc, via_stream.sheet, confirmed(), sales_options())
    assert first.fingerprint == second.fingerprint
    assert first.readiness == "READY_FOR_CHECKS" == second.readiness


def test_gl_csv_end_to_end_debit_credit_totals() -> None:
    data = (
        b"Account No.,Posting Date,Debit,Credit,Currency\n"
        b"000101,10/01/2026,500.000,,JOD\n"
        b"000202,11/01/2026,,500.000,JOD\n"
    )
    extracted = extract_bytes(
        data, declared_format="csv", doc_id="SYN-E2E-GL", csv=CsvSettings(delimiter=",")
    )
    mapping = ConfirmedMapping(
        field_map={
            "account_code": "Account No.",
            "transaction_date": "Posting Date",
            "debit_amount": "Debit",
            "credit_amount": "Credit",
            "currency": "Currency",
        },
        confirmed=True,
    )
    result = normalize_dataset(
        extracted.doc,
        extracted.sheet,
        mapping,
        NormalizationOptions(
            doc_type="general_ledger",
            decimal_separator=".",
            grouping_separator=",",
            date_format="DD/MM/YYYY",
        ),
    )
    assert result.readiness == "READY_FOR_CHECKS"
    by_field = {(t.field, t.currency): t.total for t in result.totals}
    assert by_field[("debit_amount", "JOD")] == Decimal("500.000")
    assert by_field[("credit_amount", "JOD")] == Decimal("500.000")
    assert result.rows[0].fields[0].location.row_number == 2
