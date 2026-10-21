"""Run a synthetic fixture through the pure REC-005 engine and serialize it.

The run is stateless and deterministic: the same fixture always produces the
same report/findings fingerprints for a given tenant/client, so an exported
report and the on-screen findings are computed independently but stay
consistent.
"""

from __future__ import annotations

from app.demo.fixtures import SYNTHETIC_LABEL, DemoFixture
from app.demo.summary import build_conclusion
from app.recon.findings import MoneyView
from app.recon.gl import (
    GLComparisonReport,
    GLComparisonRequest,
    GLFinding,
    GLFindingsReport,
    compare_sales_to_gl,
    project_gl,
)
from app.schemas.demo_recon import (
    DemoConclusion,
    DemoCoverage,
    DemoCurrencyResult,
    DemoEvidence,
    DemoFinding,
    DemoMoney,
    DemoReconRunOut,
)


def run_fixture(
    fixture: DemoFixture, *, tenant_id: str, client_id: str
) -> tuple[GLComparisonReport, GLFindingsReport]:
    """Execute the deterministic comparison over the synthetic fixture."""
    request = GLComparisonRequest(
        tenant_id=tenant_id,
        client_id=client_id,
        sales_dataset_id=fixture.sales_dataset_id,
        gl_dataset_id=fixture.gl_dataset_id,
        jurisdiction=fixture.jurisdiction,
        rules_version=fixture.rules_version,
        policy=fixture.policy,
        period_start=fixture.period_start,
        period_end=fixture.period_end,
    )
    report = compare_sales_to_gl(fixture.sales, fixture.gl, request)
    return report, project_gl(report)


def _money(views: tuple[MoneyView | None, ...]) -> list[DemoMoney]:
    return [DemoMoney(amount=view.amount, currency=view.currency) for view in views if view is not None]


def _finding(item: GLFinding) -> DemoFinding:
    return DemoFinding(
        finding_id=item.finding_id,
        category=item.category,
        severity=item.severity,
        review_state=item.review_state,
        review_required=item.review_required,
        rule=item.rule,
        outcome_kind=item.outcome_kind,
        title=item.title,
        what=item.what,
        compared=item.compared,
        difference=item.difference,
        why=item.why,
        guidance=item.guidance,
        sales=_money(item.sales),
        gl=_money(item.gl),
        delta=item.delta,
        delta_currency=item.delta_currency,
        evidence=[
            DemoEvidence(
                dataset_id=ref.dataset_id,
                source=ref.source,
                row_number=ref.row_number,
                raw_reference=ref.raw_reference,
                role=ref.role,  # type: ignore[arg-type]
            )
            for ref in item.evidence
        ],
        rationale=list(item.rationale),
        flags=list(item.flags),
    )


def _conclusion(report: GLComparisonReport, findings: GLFindingsReport) -> DemoConclusion:
    summary = build_conclusion(report, findings)
    return DemoConclusion(
        status=summary.status,  # type: ignore[arg-type]
        headline=summary.headline,
        detail=summary.detail,
        caution=summary.caution,
        currency_results=[
            DemoCurrencyResult(
                currency=result.currency,
                outcome=result.outcome,  # type: ignore[arg-type]
                sales_total=result.sales_total,
                gl_total=result.gl_total,
                delta=result.delta,
            )
            for result in summary.currency_results
        ],
        coverage=DemoCoverage(
            complete=summary.coverage_complete,
            scope=summary.coverage_scope,
            currencies=list(summary.coverage_currencies),
            reasons=list(summary.coverage_reasons),
            explanations=list(summary.coverage_explanations),
        ),
    )


def to_response(
    fixture: DemoFixture, report: GLComparisonReport, findings: GLFindingsReport
) -> DemoReconRunOut:
    """Build the versioned, labelled API payload for one demo run."""
    return DemoReconRunOut(
        synthetic=True,
        label=SYNTHETIC_LABEL,
        fixture_id=fixture.fixture_id,
        fixture_title=fixture.title,
        jurisdiction=report.jurisdiction,
        rules_version=report.rules_version,
        period_start=fixture.period_start,
        period_end=fixture.period_end,
        policy_id=report.policy_id,
        policy_version=report.policy_version,
        comparison_basis=report.comparison_basis,
        sales_measure=report.sales_measure,
        gl_account_scope=list(report.gl_account_scope),
        debit_credit_convention=report.debit_credit_convention,
        currency_scope=list(report.currency_scope),
        tolerance=str(report.tolerance) if report.tolerance is not None else None,
        blocked=report.blocked,
        block_reasons=list(report.block_reasons),
        inconclusive=report.inconclusive,
        inconclusive_reasons=list(report.inconclusive_reasons),
        recon_fingerprint=report.fingerprint,
        findings_fingerprint=findings.fingerprint,
        summary=dict(findings.summary),
        findings=[_finding(item) for item in findings.findings],
        conclusion=_conclusion(report, findings),
    )


__all__ = ["run_fixture", "to_response"]
