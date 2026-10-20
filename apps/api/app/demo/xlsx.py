"""XLSX renderer for the synthetic demo report (openpyxl, already pinned).

Produces a deterministic workbook with a mandatory synthetic-label row on every
sheet: ``Summary`` (fixture + policy + run metadata and counts), ``Findings``
(the accountant-facing review items) and ``Evidence`` (per-finding source-row
pointers). No I/O beyond an in-memory buffer.
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook  # type: ignore[import-untyped]
from openpyxl.styles import Font  # type: ignore[import-untyped]

from app.demo.fixtures import SYNTHETIC_LABEL, DemoFixture
from app.recon.gl import GLComparisonReport, GLFindingsReport

_BOLD = Font(bold=True)


def _summary_sheet(
    ws,
    fixture: DemoFixture,
    report: GLComparisonReport,
    findings: GLFindingsReport,
    engagement_period: tuple[str, str] | None,
) -> None:
    rows: list[tuple[str, str]] = [
        ("Fixture", fixture.title),
        ("Fixture id", fixture.fixture_id),
        ("Jurisdiction", report.jurisdiction),
        ("Rules version", report.rules_version),
        (
            "Engagement period",
            f"{engagement_period[0]} to {engagement_period[1]}" if engagement_period else "not supplied",
        ),
        (
            "Fixture comparison period",
            f"{fixture.period_start.isoformat()} to {fixture.period_end.isoformat()}",
        ),
        ("Comparison basis", str(report.comparison_basis)),
        ("Sales measure", str(report.sales_measure)),
        ("Debit/credit convention", str(report.debit_credit_convention)),
        ("GL account scope", ", ".join(report.gl_account_scope)),
        ("Currency scope", ", ".join(report.currency_scope)),
        ("Tolerance", str(report.tolerance)),
        ("Blocked", str(report.blocked)),
        ("Inconclusive", str(report.inconclusive)),
        ("Inconclusive reasons", ", ".join(report.inconclusive_reasons)),
        ("Sales rows", str(report.sales_total)),
        ("GL rows", str(report.gl_total)),
        ("Reconciliation fingerprint", report.fingerprint),
        ("Findings fingerprint", findings.fingerprint),
        ("Findings total", str(findings.summary.get("total", 0))),
        ("Findings review-required", str(findings.summary.get("review_required", 0))),
        ("Findings informational", str(findings.summary.get("informational", 0))),
    ]
    ws["A1"] = SYNTHETIC_LABEL
    ws["A1"].font = _BOLD
    for offset, (key, value) in enumerate(rows, start=3):
        ws.cell(row=offset, column=1, value=key).font = _BOLD
        ws.cell(row=offset, column=2, value=value)
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 72


def _findings_sheet(ws, findings: GLFindingsReport) -> None:
    headers = [
        "#",
        "finding_id",
        "category",
        "severity",
        "outcome_kind",
        "review_required",
        "title",
        "what",
        "compared",
        "difference",
        "why",
        "guidance",
        "delta",
        "delta_currency",
        "rule",
    ]
    ws["A1"] = SYNTHETIC_LABEL
    ws["A1"].font = _BOLD
    for col, name in enumerate(headers, start=1):
        ws.cell(row=3, column=col, value=name).font = _BOLD
    for index, item in enumerate(findings.findings, start=1):
        row = 3 + index
        values = [
            index,
            item.finding_id,
            item.category,
            item.severity,
            item.outcome_kind,
            str(item.review_required),
            item.title,
            item.what,
            item.compared,
            item.difference,
            item.why,
            item.guidance,
            item.delta or "",
            item.delta_currency or "",
            item.rule,
        ]
        for col, value in enumerate(values, start=1):
            ws.cell(row=row, column=col, value=value)


def _evidence_sheet(ws, findings: GLFindingsReport) -> None:
    headers = ["finding_id", "role", "dataset_id", "source", "row_number", "raw_reference"]
    ws["A1"] = SYNTHETIC_LABEL
    ws["A1"].font = _BOLD
    for col, name in enumerate(headers, start=1):
        ws.cell(row=3, column=col, value=name).font = _BOLD
    row = 4
    for item in findings.findings:
        for ref in item.evidence:
            values = [
                item.finding_id,
                ref.role,
                ref.dataset_id,
                ref.source,
                ref.row_number,
                ref.raw_reference,
            ]
            for col, value in enumerate(values, start=1):
                ws.cell(row=row, column=col, value=value)
            row += 1


def build_xlsx(
    fixture: DemoFixture,
    report: GLComparisonReport,
    findings: GLFindingsReport,
    *,
    engagement_period: tuple[str, str] | None = None,
) -> bytes:
    """Render the demo run into an in-memory XLSX workbook.

    ``engagement_period`` is display-only context: the calculation always uses
    the fixture's own comparison period, which the Summary sheet states
    explicitly so the two can never be conflated.
    """
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Summary"
    _summary_sheet(summary, fixture, report, findings, engagement_period)
    _findings_sheet(workbook.create_sheet("Findings"), findings)
    _evidence_sheet(workbook.create_sheet("Evidence"), findings)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


__all__ = ["build_xlsx"]
