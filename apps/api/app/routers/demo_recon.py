"""REC-UI-01 restricted synthetic-demo reconciliation boundary.

A deliberately narrow, opt-in (``TAXPILOT_DEMO_RECON_ENABLED``) surface that runs
the *existing* pure REC-005 engine over static, server-side synthetic fixtures
so the accountant-facing journey can be demonstrated end to end. It is not the
production reconciliation path and changes none of its gates:

- fixture-only: the request names a known synthetic fixture; no dataset version
  ids, no uploaded content, no quarantine reads, no dataset/mapping/release rows
  are touched, and nothing is enqueued or persisted;
- tenant-scoped and authenticated: cookie/bearer session required, and the
  engagement must belong to the caller's tenant (cross-tenant -> 404);
- refused entirely when disabled (403 ``DEMO_NOT_ENABLED``) and forced off in
  production by config;
- the real ``/recon-runs`` boundary stays default-deny and unchanged.

Exports are deterministic re-runs of the same fixture, so the on-screen findings
and the exported documents share a stable fingerprint.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response

from ..demo import fixtures as demo_fixtures
from ..demo.pdf import Line, build_pdf
from ..demo.service import run_fixture, to_response
from ..demo.summary import build_conclusion, ordered_findings
from ..demo.xlsx import build_xlsx
from ..deps import settings_singleton
from ..errors import AppError
from ..recon.gl import GLComparisonReport, GLFindingsReport
from ..schemas.demo_recon import DemoFixtureOut, DemoReconRunIn, DemoReconRunOut
from ..sprint1_auth import WRITE, CurrentUser, open_store, require_roles, require_tenant, tenant_of

router = APIRouter(tags=["demo-recon"])

# The synthetic boundary refuses engagements in terminal states, mirroring the
# real run boundary's refusal to act on closed/archived work.
_RUNNABLE_STATES = ("DRAFT", "ACTIVE")

_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_PDF_FOOTER = "Synthetic demo data - not customer records / not a tax filing"


def _require_enabled() -> None:
    if not settings_singleton().demo_recon_enabled:
        raise AppError(
            "FORBIDDEN",
            "Synthetic demo reconciliation is not enabled on this environment.",
            {"reason": "DEMO_NOT_ENABLED"},
        )


def _uuid_or_404(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise AppError("NOT_FOUND", "Engagement not found.") from None


def _fixture_or_422(fixture_id: str) -> demo_fixtures.DemoFixture:
    fixture = demo_fixtures.get_fixture(fixture_id)
    if fixture is None:
        raise AppError("VALIDATION_ERROR", "Unknown synthetic fixture.", {"fixture_id": fixture_id})
    return fixture


def _engagement_or_404(store, tenant_id: str, engagement_id: str) -> dict:  # type: ignore[no-untyped-def]
    engagement = store.get_engagement(_uuid_or_404(engagement_id), tenant_id)
    if engagement is None:
        raise AppError("NOT_FOUND", "Engagement not found.")
    return engagement


def _assert_runnable(engagement: dict) -> None:
    if engagement["status"] not in _RUNNABLE_STATES:
        raise AppError(
            "STATE_CONFLICT",
            "Engagement is not runnable for the synthetic demo.",
            {"reason": "DEMO_ENGAGEMENT_STATE", "status": engagement["status"]},
        )


@router.get("/demo-recon/fixtures", response_model=list[DemoFixtureOut])
def list_demo_fixtures(user: CurrentUser = Depends(require_tenant)) -> list[DemoFixtureOut]:
    """Read-only descriptions of the available synthetic scenarios."""
    _require_enabled()
    return [
        DemoFixtureOut(
            fixture_id=fixture.fixture_id,
            title=fixture.title,
            description=fixture.description,
            jurisdiction=fixture.jurisdiction,
            rules_version=fixture.rules_version,
            period_start=fixture.period_start,
            period_end=fixture.period_end,
            sales_dataset_id=fixture.sales_dataset_id,
            gl_dataset_id=fixture.gl_dataset_id,
            account_scope=list(fixture.policy.gl_account_scope),
            currency_scope=list(fixture.policy.currency_scope),
        )
        for fixture in demo_fixtures.FIXTURES.values()
    ]


@router.post("/engagements/{engagement_id}/demo-recon-runs", response_model=DemoReconRunOut)
def run_demo_recon(
    engagement_id: str,
    body: DemoReconRunIn,
    request: Request,
    user: CurrentUser = Depends(require_roles(*WRITE)),
) -> DemoReconRunOut:
    """Run one synthetic fixture in memory and return labelled findings."""
    _require_enabled()
    fixture = _fixture_or_422(body.fixture_id)
    tenant_id = tenant_of(user)
    store, conn, _ = open_store(request)
    try:
        engagement = _engagement_or_404(store, tenant_id, engagement_id)
        _assert_runnable(engagement)
    finally:
        conn.close()
    report, findings = run_fixture(fixture, tenant_id=tenant_id, client_id=str(engagement["client_id"]))
    return to_response(fixture, report, findings)


def _money_text(amount: str | None, currency: str | None) -> str:
    if amount is None:
        return "-"
    return f"{amount} {currency}" if currency else amount


def _period_text(value: object) -> str:
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


def _engagement_period(engagement: dict) -> tuple[str, str]:
    return (_period_text(engagement.get("period_start")), _period_text(engagement.get("period_end")))


def _pdf_lines(
    fixture: demo_fixtures.DemoFixture,
    report: GLComparisonReport,
    findings: GLFindingsReport,
    engagement: dict,
) -> list[Line]:
    eng_start, eng_end = _engagement_period(engagement)
    conclusion = build_conclusion(report, findings)
    lines: list[Line] = [
        Line(demo_fixtures.SYNTHETIC_LABEL_ASCII, size=12, font="F2"),
        Line(""),
        Line(fixture.title, size=14),
        Line(f"Synthetic fixture: {fixture.fixture_id}"),
        Line(f"Jurisdiction: {report.jurisdiction}    Rules version: {report.rules_version}"),
        Line(f"Engagement period: {eng_start} to {eng_end}"),
        Line(
            f"Fixture comparison period: {fixture.period_start.isoformat()} "
            f"to {fixture.period_end.isoformat()}"
        ),
        Line(
            f"Basis: {report.comparison_basis}    Measure: {report.sales_measure}    "
            f"Convention: {report.debit_credit_convention}"
        ),
        Line(
            f"Account scope: {', '.join(report.gl_account_scope)}    "
            f"Currency scope: {', '.join(report.currency_scope)}"
        ),
        Line(f"Tolerance: {report.tolerance}    Inconclusive: {report.inconclusive}"),
        Line(f"Recon fingerprint: {report.fingerprint}"),
        Line(f"Findings fingerprint: {findings.fingerprint}"),
        Line(f"Sales rows: {report.sales_total}    GL rows: {report.gl_total}"),
        Line(""),
        Line("RESULT SUMMARY", size=12),
        Line(conclusion.headline, size=11),
        Line(conclusion.detail),
        Line(
            f"Review required: {findings.summary.get('review_required', 0)}    "
            f"Informational: {findings.summary.get('informational', 0)}"
        ),
    ]
    for result in conclusion.currency_results:
        if result.outcome == "DIFFERENCE":
            lines.append(
                Line(
                    f"{result.currency}: sales {result.sales_total}, GL {result.gl_total}, "
                    f"difference {result.delta} (tolerance {report.tolerance})"
                )
            )
        else:
            lines.append(Line(f"{result.currency}: coverage incomplete - no conclusion stated"))
    if conclusion.coverage_reasons:
        lines.append(
            Line(
                "Coverage reasons: "
                + "; ".join(
                    f"{reason} ({text})"
                    for reason, text in zip(
                        conclusion.coverage_reasons, conclusion.coverage_explanations, strict=False
                    )
                )
            )
        )
    lines.extend([Line(f"Caution: {conclusion.caution}"), Line("")])

    lines.append(Line(f"FINDINGS ({findings.summary.get('total', 0)})", size=12))
    for index, item in enumerate(ordered_findings(findings.findings), start=1):
        label = "REVIEW REQUIRED" if item.review_required else "INFORMATIONAL"
        lines.append(Line(f"{index}. [{item.severity} / {label}] {item.title}", size=11))
        lines.append(Line(f"   What we compared: {item.compared}"))
        lines.append(Line(f"   What we found: {item.difference}"))
        lines.append(Line(f"   Why this matters: {item.why}"))
        lines.append(Line(f"   What to check next: {item.guidance}"))
        if item.delta is not None:
            lines.append(Line(f"   Delta: {_money_text(item.delta, item.delta_currency)}"))
        lines.append(Line(f"   Rule {item.rule}    Kind {item.outcome_kind}    Category {item.category}"))
        for ref in item.evidence:
            side = "Sales register" if ref.role == "sales" else "General ledger"
            lines.append(
                Line(f"   Evidence: {side} | {ref.dataset_id} row {ref.row_number} | {ref.raw_reference}")
            )
        if item.rationale:
            lines.append(Line(f"   Rationale: {'; '.join(item.rationale)}"))
        if item.flags:
            lines.append(Line(f"   Flags: {', '.join(item.flags)}"))
        lines.append(Line(""))

    lines.extend(
        [
            Line("REPORT NOTES", size=12),
            Line("Report language: English only (PDF and XLSX)."),
            Line("Source rows belong to the built-in synthetic scenario, not client files."),
            Line(
                "Generated deterministically from static synthetic fixtures. No customer data.",
                font="F2",
            ),
        ]
    )
    return lines


def _assert_export_matches_display(
    recon_fingerprint: str,
    findings_fingerprint: str,
    expected_recon_fingerprint: str | None,
    expected_findings_fingerprint: str | None,
) -> None:
    if expected_recon_fingerprint is not None and expected_recon_fingerprint != recon_fingerprint:
        raise AppError(
            "STATE_CONFLICT",
            "Export request does not match the displayed run.",
            {"reason": "DEMO_FINGERPRINT_MISMATCH", "field": "recon_fingerprint"},
        )
    if expected_findings_fingerprint is not None and expected_findings_fingerprint != findings_fingerprint:
        raise AppError(
            "STATE_CONFLICT",
            "Export request does not match the displayed run.",
            {"reason": "DEMO_FINGERPRINT_MISMATCH", "field": "findings_fingerprint"},
        )


@router.get("/engagements/{engagement_id}/demo-recon-runs/report")
def export_demo_recon(
    engagement_id: str,
    request: Request,
    fixture_id: str = Query(min_length=1, max_length=64),
    format: str = Query(default="pdf", pattern="^(pdf|xlsx)$"),
    expected_recon_fingerprint: str | None = Query(default=None, min_length=1, max_length=64),
    expected_findings_fingerprint: str | None = Query(default=None, min_length=1, max_length=64),
    user: CurrentUser = Depends(require_tenant),
) -> Response:
    """Deterministically render the demo run as a labelled PDF or XLSX file.

    When the caller supplies the fingerprints of the run currently displayed,
    the export refuses to render a different calculation: this binds the
    downloaded document to the exact on-screen result (see REC-UI-01 F1).
    """
    _require_enabled()
    fixture = _fixture_or_422(fixture_id)
    tenant_id = tenant_of(user)
    store, conn, _ = open_store(request)
    try:
        engagement = _engagement_or_404(store, tenant_id, engagement_id)
        _assert_runnable(engagement)
    finally:
        conn.close()
    report, findings = run_fixture(fixture, tenant_id=tenant_id, client_id=str(engagement["client_id"]))
    _assert_export_matches_display(
        report.fingerprint, findings.fingerprint, expected_recon_fingerprint, expected_findings_fingerprint
    )
    filename = f"synthetic-recon-{fixture.fixture_id}-{findings.fingerprint[:12]}.{format}"
    if format == "xlsx":
        content = build_xlsx(fixture, report, findings, engagement_period=_engagement_period(engagement))
        media_type = _XLSX_MEDIA
    else:
        content = build_pdf(_pdf_lines(fixture, report, findings, engagement), footer=_PDF_FOOTER)
        media_type = "application/pdf"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
