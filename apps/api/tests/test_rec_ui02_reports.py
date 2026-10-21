"""REC-UI-02 report readability and safety (pure, no DB).

Covers the accountant-facing defects found in the browser audit: long text
running off the PDF page, no page footer, unformatted spreadsheets, and text
cells that could be interpreted as formulas.
"""

from dataclasses import replace
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]

from app.demo.fixtures import SYNTHETIC_LABEL, DemoFixture, get_fixture
from app.demo.pdf import Line, build_pdf, wrap_lines
from app.demo.service import run_fixture, to_response
from app.demo.summary import build_conclusion, ordered_findings
from app.demo.xlsx import _write, build_xlsx
from app.recon.gl import (
    GLComparisonReport,
    GLComparisonRequest,
    GLFindingsReport,
    compare_sales_to_gl,
    project_gl,
)
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


def _run_v2() -> tuple[DemoFixture, GLComparisonReport, GLFindingsReport]:
    fixture = get_fixture("synthetic-sales-gl-v2")
    assert fixture is not None
    report, findings = run_fixture(fixture, tenant_id="t1", client_id="c1")
    return fixture, report, findings


def test_whole_run_uncertainty_is_never_complete_and_never_invents_a_currency() -> None:
    fixture, _, _ = _run_v2()
    altered = replace(
        fixture,
        sales=(replace(fixture.sales[0], currency=None),),
        gl=(),
    )
    report, findings = run_fixture(altered, tenant_id="t1", client_id="c1")
    conclusion = build_conclusion(report, findings)

    assert report.inconclusive is True
    assert report.inconclusive_reasons == ("COVERAGE_MISSING_CURRENCY",)
    assert conclusion.coverage_complete is False
    assert conclusion.coverage_scope == "WHOLE_RUN"
    assert conclusion.coverage_currencies == ()
    assert conclusion.coverage_reasons == ("COVERAGE_MISSING_CURRENCY",)
    assert conclusion.currency_results == ()
    assert "whole comparison" in conclusion.detail

    response = to_response(altered, report, findings)
    assert response.conclusion.coverage.complete is False
    assert response.conclusion.coverage.scope == "WHOLE_RUN"
    assert response.conclusion.coverage.currencies == []
    assert response.conclusion.coverage.reasons == ["COVERAGE_MISSING_CURRENCY"]

    known_currency = replace(fixture, sales=(replace(fixture.sales[0], currency=None),))
    known_report, known_findings = run_fixture(known_currency, tenant_id="t1", client_id="c1")
    known_conclusion = build_conclusion(known_report, known_findings)
    assert known_report.inconclusive is True
    assert known_conclusion.coverage_complete is False
    assert known_conclusion.coverage_scope == "WHOLE_RUN"
    assert known_conclusion.coverage_currencies == ("JOD",)
    assert "whole comparison" in known_conclusion.detail


def test_exports_show_whole_run_uncertainty_as_incomplete_coverage() -> None:
    fixture, _, _ = _run_v2()
    altered = replace(
        fixture,
        sales=(replace(fixture.sales[0], currency=None),),
        gl=(),
    )
    report, findings = run_fixture(altered, tenant_id="t1", client_id="c1")
    engagement = {"period_start": "2026-02-01", "period_end": "2026-06-30"}
    pdf = build_pdf(_pdf_lines(altered, report, findings, engagement), footer=FOOTER).decode("latin-1")
    assert "Coverage: incomplete for the whole comparison" in pdf

    workbook = load_workbook(BytesIO(build_xlsx(altered, report, findings)))
    summary = workbook["Summary"]
    rows = {
        summary.cell(row=row, column=1).value: summary.cell(row=row, column=2).value
        for row in range(3, summary.max_row + 1)
    }
    assert rows["Coverage complete"] == "False"
    assert "whole comparison" in rows["Coverage scope"]


def test_blocked_run_never_reports_complete_coverage() -> None:
    fixture, _, _ = _run_v2()
    request = GLComparisonRequest(
        tenant_id="t1",
        client_id="c1",
        sales_dataset_id=fixture.sales_dataset_id,
        gl_dataset_id=fixture.gl_dataset_id,
        jurisdiction=fixture.jurisdiction,
        rules_version=fixture.rules_version,
        policy=None,
        period_start=fixture.period_start,
        period_end=fixture.period_end,
    )
    report = compare_sales_to_gl(fixture.sales, fixture.gl, request)
    findings = project_gl(report)
    conclusion = build_conclusion(report, findings)

    assert report.blocked is True
    assert conclusion.coverage_complete is False
    assert conclusion.coverage_scope == "BLOCKED"
    assert conclusion.coverage_currencies == ()
    assert conclusion.status == "BLOCKED"

    response = to_response(fixture, report, findings)
    assert response.conclusion.coverage.complete is False
    assert response.conclusion.coverage.scope == "BLOCKED"

    pdf = build_pdf(
        _pdf_lines(fixture, report, findings, {"period_start": "2026-02-01", "period_end": "2026-06-30"}),
        footer=FOOTER,
    ).decode("latin-1")
    assert "Coverage: not established" in pdf
    workbook = load_workbook(BytesIO(build_xlsx(fixture, report, findings)))
    summary = workbook["Summary"]
    rows = {
        summary.cell(row=row, column=1).value: summary.cell(row=row, column=2).value
        for row in range(3, summary.max_row + 1)
    }
    assert rows["Coverage complete"] == "False"
    assert rows["Coverage scope"].startswith("not established")


def test_genuinely_complete_run_reports_complete_coverage() -> None:
    _, report, findings = _run_v2()
    conclusion = build_conclusion(report, findings)

    assert report.blocked is False
    assert report.inconclusive is False
    assert conclusion.coverage_complete is True
    assert conclusion.coverage_scope == "COMPLETE"
    assert [(item.currency, item.outcome) for item in conclusion.currency_results] == [("JOD", "DIFFERENCE")]


def test_currency_results_include_reconciled_and_missing_side_outcomes() -> None:
    fixture, _, _ = _run_v2()

    reconciled = replace(
        fixture,
        gl=(replace(fixture.gl[0], credit=Decimal("1500.000")),),
    )
    reconciled_report, reconciled_findings = run_fixture(reconciled, tenant_id="t1", client_id="c1")
    reconciled_conclusion = build_conclusion(reconciled_report, reconciled_findings)
    assert [
        (item.currency, item.outcome, item.sales_total, item.gl_total, item.delta)
        for item in reconciled_conclusion.currency_results
    ] == [("JOD", "RECONCILED", "1500.000", "1500.000", "0.000")]
    reconciled_response = to_response(reconciled, reconciled_report, reconciled_findings)
    assert reconciled_response.conclusion.currency_results[0].outcome == "RECONCILED"

    missing_gl = replace(fixture, gl=())
    missing_gl_report, missing_gl_findings = run_fixture(missing_gl, tenant_id="t1", client_id="c1")
    missing_gl_conclusion = build_conclusion(missing_gl_report, missing_gl_findings)
    assert [(item.currency, item.outcome) for item in missing_gl_conclusion.currency_results] == [
        ("JOD", "MISSING_GL")
    ]
    assert missing_gl_conclusion.currency_results[0].sales_total is None
    missing_gl_response = to_response(missing_gl, missing_gl_report, missing_gl_findings)
    assert missing_gl_response.conclusion.currency_results[0].outcome == "MISSING_GL"

    missing_sales = replace(fixture, sales=())
    missing_sales_report, missing_sales_findings = run_fixture(missing_sales, tenant_id="t1", client_id="c1")
    missing_sales_conclusion = build_conclusion(missing_sales_report, missing_sales_findings)
    assert [(item.currency, item.outcome) for item in missing_sales_conclusion.currency_results] == [
        ("JOD", "MISSING_SALES")
    ]
    assert missing_sales_conclusion.currency_results[0].gl_total is None
