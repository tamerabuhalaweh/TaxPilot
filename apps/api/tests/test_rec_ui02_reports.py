"""REC-UI-02 report readability and safety (pure, no DB).

Covers the accountant-facing defects found in the browser audit: long text
running off the PDF page, no page footer, unformatted spreadsheets, and text
cells that could be interpreted as formulas.
"""

from io import BytesIO

from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]

from app.demo.fixtures import SYNTHETIC_LABEL, DemoFixture, get_fixture
from app.demo.pdf import Line, build_pdf, wrap_lines
from app.demo.service import run_fixture
from app.demo.summary import build_conclusion, ordered_findings
from app.demo.xlsx import _write, build_xlsx
from app.recon.gl import GLComparisonReport, GLFindingsReport
from app.routers.demo_recon import _pdf_lines

FIXTURE_ID = "synthetic-sales-gl-v1"
FOOTER = "Synthetic demo data - not customer records / not a tax filing"


def _run() -> tuple[DemoFixture, GLComparisonReport, GLFindingsReport]:
    fixture = get_fixture(FIXTURE_ID)
    assert fixture is not None
    report, findings = run_fixture(fixture, tenant_id="t1", client_id="c1")
    return fixture, report, findings


def test_pdf_wraps_long_tokens_before_paginating() -> None:
    token = "X" * 400
    pdf = build_pdf(
        [
            Line(f"Label {token}"),
            *[Line(f"line {index}") for index in range(200)],
        ],
        footer=FOOTER,
    )
    assert pdf.startswith(b"%PDF-")
    assert pdf.count(b"/Type /Page ") >= 2
    # The unbroken token cannot be emitted as one printable line.
    assert token.encode("ascii") not in pdf
    assert b"line 199" in pdf
    assert b"Page 1 of " in pdf


def test_pdf_wrapping_preserves_indentation_and_blank_lines() -> None:
    wrapped = wrap_lines([Line("   " + "word " * 60), Line("")])
    assert wrapped[0].text.startswith("   ")
    assert wrapped[-1].text == ""
    assert len(wrapped) > 2


def test_demo_pdf_contains_a_structured_result_summary() -> None:
    fixture, report, findings = _run()
    engagement = {"period_start": "2026-02-01", "period_end": "2026-06-30"}
    pdf = build_pdf(_pdf_lines(fixture, report, findings, engagement), footer=FOOTER).decode("latin-1")
    assert "RESULT SUMMARY" in pdf
    assert "Review required" in pdf
    assert "Coverage is incomplete for USD" in pdf
    assert "Caution: Equal totals do not prove completeness" in pdf
    assert "What we compared:" in pdf
    assert "What to check next:" in pdf
    assert "Sales register | SYNTHETIC-SALES-v1 row" in pdf
    assert "REPORT NOTES" in pdf
    assert "Report language: English only" in pdf
    assert "Page 1 of" in pdf


def test_demo_xlsx_is_formatted_and_review_first() -> None:
    fixture, report, findings = _run()
    data = build_xlsx(fixture, report, findings)
    workbook = load_workbook(BytesIO(data))

    summary = workbook["Summary"]
    rows = {
        summary.cell(row=row, column=1).value: summary.cell(row=row, column=2).value
        for row in range(3, summary.max_row + 1)
    }
    assert rows["Review conclusion"] == "Review required"
    assert "Coverage is incomplete for USD" in rows["Conclusion detail"]
    assert rows["Coverage complete"] == "False"
    assert "JOD: sales 3500.000, GL 3400.000, difference 100.000" in rows["Currency results"]
    assert rows["Report language"] == "English only (PDF and XLSX)"
    assert rows["Synthetic label"] == SYNTHETIC_LABEL
    assert summary.freeze_panes == "A3"

    sheet = workbook["Findings"]
    assert sheet.freeze_panes == "A4"
    assert sheet.auto_filter.ref
    assert sheet.column_dimensions["G"].width and sheet.column_dimensions["G"].width > 20
    first_row = [sheet.cell(row=4, column=col).value for col in range(1, sheet.max_column + 1)]
    assert first_row[4] == "DIFFERENCE"
    assert first_row[3] == "HIGH"
    assert first_row[11] and len(str(first_row[11])) > 20

    evidence = workbook["Evidence"]
    assert evidence.freeze_panes == "A4"
    assert evidence.auto_filter.ref
    assert evidence.cell(row=4, column=7).value in {"Sales register", "General ledger"}


def test_xlsx_text_cells_are_never_formulas() -> None:
    workbook = Workbook()
    sheet = workbook.active
    for row, value in enumerate(["=1+1", "+SUM(A1)", "-2+3", "@cmd", "plain"], start=1):
        _write(sheet, row, 1, value)
    buffer = BytesIO()
    workbook.save(buffer)
    saved = load_workbook(BytesIO(buffer.getvalue())).active
    for row, value in enumerate(["=1+1", "+SUM(A1)", "-2+3", "@cmd", "plain"], start=1):
        cell = saved.cell(row=row, column=1)
        assert cell.value == value
        assert cell.data_type == "s", f"cell {row} must remain text"


def test_summary_orders_review_items_before_information() -> None:
    _, report, findings = _run()
    ordered = ordered_findings(findings.findings)
    review_flags = [item.review_required for item in ordered]
    assert review_flags == sorted(review_flags, reverse=True)
    conclusion = build_conclusion(report, findings)
    assert conclusion.status == "REVIEW_REQUIRED"
    assert conclusion.coverage_currencies == ("USD",)
    assert conclusion.coverage_reasons == ("COVERAGE_DUPLICATE",)
    assert [item.currency for item in conclusion.currency_results] == ["JOD", "USD"]
    assert conclusion.caution.startswith("Equal totals do not prove completeness")
