"""Plain-language result summary shared by the demo API and both exports.

The engine returns exact decimals and code-shaped metadata; accountants need a
short, honest read of *what the run concluded* without turning the UI into a
second calculation. This module derives presentation-only facts from the
already-computed findings:

- an overall status that never asserts more than the engine proved;
- the currency-level outcomes the engine actually emitted, with exact totals
  only where the engine supplied them;
- the affected currencies and reasons when coverage was incomplete, including
  whole-run uncertainty whose currency could not be established.

Nothing here changes a verdict, an amount, or a fingerprint. Equal totals are
explicitly not treated as proof of completeness, and coverage completeness comes
from the authoritative report rather than from its currency presentation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from app.recon.gl import GLComparisonReport, GLFinding, GLFindingsReport
from app.recon.gl.contracts import (
    COVERAGE_CURRENCY_OUT_OF_SCOPE,
    COVERAGE_MISSING_CURRENCY,
    DIFFERENCE,
    INCONCLUSIVE_COVERAGE,
    MISSING_GL,
    MISSING_SALES,
    RECONCILED,
)

STATUS_BLOCKED = "BLOCKED"
STATUS_REVIEW_REQUIRED = "REVIEW_REQUIRED"
STATUS_NO_REVIEW_ITEMS = "NO_REVIEW_ITEMS"

CoverageScope = Literal["COMPLETE", "CURRENCIES", "WHOLE_RUN", "BLOCKED"]

COVERAGE_SCOPE_COMPLETE: Final[CoverageScope] = "COMPLETE"
COVERAGE_SCOPE_CURRENCIES: Final[CoverageScope] = "CURRENCIES"
COVERAGE_SCOPE_WHOLE_RUN: Final[CoverageScope] = "WHOLE_RUN"
COVERAGE_SCOPE_BLOCKED: Final[CoverageScope] = "BLOCKED"

_CURRENCY_OUTCOMES = frozenset({RECONCILED, DIFFERENCE, MISSING_GL, MISSING_SALES, INCONCLUSIVE_COVERAGE})
_GLOBAL_COVERAGE_REASONS = frozenset({COVERAGE_MISSING_CURRENCY, COVERAGE_CURRENCY_OUT_OF_SCOPE})

CAUTION = (
    "Equal totals do not prove completeness: rows can be missing, duplicated, "
    "or recorded outside the period. Confirm coverage against both source "
    "registers before relying on this result."
)

_REASON_TEXT = {
    "COVERAGE_MISSING_CURRENCY": "a source row is missing its currency",
    "COVERAGE_CURRENCY_OUT_OF_SCOPE": "a source row uses a currency outside the scenario scope",
    "COVERAGE_INVALID_DEBIT_CREDIT_PAIR": "a ledger pair is not a valid debit/credit entry",
    "COVERAGE_MISSING_AMOUNT": "a source row is missing its amount",
    "COVERAGE_MISSING_MEASURE": "a source row is missing the value used for comparison",
    "COVERAGE_PERIOD_UNKNOWN": "a source row has no usable transaction date",
    "COVERAGE_DUPLICATE": "duplicate source rows could not be resolved automatically",
    "COVERAGE_UNVERIFIED_RELATIONSHIP": (
        "a credit note or reversal could not be linked to its original document"
    ),
}


@dataclass(frozen=True)
class CurrencyResult:
    """One currency-level outcome emitted by the reconciliation engine."""

    currency: str
    outcome: str
    sales_total: str | None
    gl_total: str | None
    delta: str | None


@dataclass(frozen=True)
class Conclusion:
    status: str
    headline: str
    detail: str
    caution: str
    currency_results: tuple[CurrencyResult, ...]
    coverage_currencies: tuple[str, ...]
    coverage_reasons: tuple[str, ...]
    coverage_explanations: tuple[str, ...]
    coverage_scope: CoverageScope

    @property
    def coverage_complete(self) -> bool:
        return self.coverage_scope == COVERAGE_SCOPE_COMPLETE


def _decimal_text(value: object | None) -> str | None:
    return None if value is None else str(value)


def _explain(reason: str) -> str:
    return _REASON_TEXT.get(reason, "a source record could not be placed or validated")


_SEVERITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def ordered_findings(findings: tuple[GLFinding, ...]) -> tuple[GLFinding, ...]:
    """Review-required first (high severity first), informational last.

    Presentation only: the underlying projection, fingerprints and amounts are
    untouched. The stable sort keeps engine order within equal keys.
    """
    return tuple(
        item
        for _, item in sorted(
            enumerate(findings),
            key=lambda pair: (
                not pair[1].review_required,
                _SEVERITY_RANK.get(pair[1].severity, 3),
                pair[0],
            ),
        )
    )


def build_conclusion(report: GLComparisonReport, findings: GLFindingsReport) -> Conclusion:
    """Derive the demo's presentation summary from an existing run."""
    currency_results = tuple(
        CurrencyResult(
            currency=outcome.currency,
            outcome=outcome.kind,
            sales_total=_decimal_text(outcome.sales_total),
            gl_total=_decimal_text(outcome.gl_total),
            delta=_decimal_text(outcome.delta),
        )
        for outcome in report.outcomes
        if outcome.kind in _CURRENCY_OUTCOMES and outcome.currency is not None
    )

    coverage_currencies = tuple(
        dict.fromkeys(
            outcome.currency
            for outcome in report.outcomes
            if outcome.kind == INCONCLUSIVE_COVERAGE and outcome.currency is not None
        )
    )
    coverage_reasons = tuple(report.inconclusive_reasons)
    coverage_explanations = tuple(_explain(reason) for reason in coverage_reasons)
    coverage_scope: CoverageScope
    if report.blocked:
        coverage_scope = COVERAGE_SCOPE_BLOCKED
    elif report.inconclusive and _GLOBAL_COVERAGE_REASONS.intersection(coverage_reasons):
        coverage_scope = COVERAGE_SCOPE_WHOLE_RUN
    elif report.inconclusive and coverage_currencies:
        coverage_scope = COVERAGE_SCOPE_CURRENCIES
    elif report.inconclusive:
        coverage_scope = COVERAGE_SCOPE_WHOLE_RUN
    else:
        coverage_scope = COVERAGE_SCOPE_COMPLETE

    review_required_value = findings.summary.get("review_required", 0)
    review_required = review_required_value if isinstance(review_required_value, int) else 0

    if report.blocked:
        status = STATUS_BLOCKED
        headline = "Blocked by policy"
        detail = (
            "The run was refused before comparison, so no result is available. "
            + (f"Reasons: {', '.join(report.block_reasons)}." if report.block_reasons else "")
        ).strip()
    elif review_required:
        status = STATUS_REVIEW_REQUIRED
        parts: list[str] = []
        differing = [item.currency for item in currency_results if item.outcome == DIFFERENCE]
        if differing:
            noun = "currency differs" if len(differing) == 1 else "currencies differ"
            parts.append(f"{len(differing)} {noun} beyond tolerance: {', '.join(differing)}.")
        missing_gl = [item.currency for item in currency_results if item.outcome == MISSING_GL]
        if missing_gl:
            noun = "currency has" if len(missing_gl) == 1 else "currencies have"
            joined = ", ".join(missing_gl)
            parts.append(f"{len(missing_gl)} {noun} sales activity but no in-scope GL posting: {joined}.")
        missing_sales = [item.currency for item in currency_results if item.outcome == MISSING_SALES]
        if missing_sales:
            noun = "currency has" if len(missing_sales) == 1 else "currencies have"
            joined = ", ".join(missing_sales)
            parts.append(f"{len(missing_sales)} {noun} GL activity but no sales counterpart: {joined}.")
        if coverage_scope == COVERAGE_SCOPE_CURRENCIES:
            if len(coverage_currencies) == 1:
                parts.append(
                    f"Coverage is incomplete for {coverage_currencies[0]}, so no conclusion "
                    "is stated for that currency."
                )
            else:
                parts.append(
                    f"Coverage is incomplete for {', '.join(coverage_currencies)}, so no "
                    "conclusion is stated for those currencies."
                )
        elif coverage_scope == COVERAGE_SCOPE_WHOLE_RUN:
            parts.append(
                "Coverage is incomplete for the whole comparison because the affected "
                "currency could not be established, so no currency conclusion is stated."
            )
        if not parts:
            parts.append(f"{review_required} review-required items need an accountant's attention.")
        headline = "Review required"
        detail = " ".join(parts)
    else:
        status = STATUS_NO_REVIEW_ITEMS
        headline = "No review-required items"
        detail = (
            "Every in-scope row was placed and compared under the scenario policy; "
            "informational items are retained for traceability."
        )

    return Conclusion(
        status=status,
        headline=headline,
        detail=detail,
        caution=CAUTION,
        currency_results=currency_results,
        coverage_currencies=coverage_currencies,
        coverage_reasons=coverage_reasons,
        coverage_explanations=coverage_explanations,
        coverage_scope=coverage_scope,
    )


def coverage_scope_text(conclusion: Conclusion) -> str:
    """English export wording for the authoritative coverage scope."""
    if conclusion.coverage_scope == COVERAGE_SCOPE_BLOCKED:
        return "not established - the run was blocked before comparison"
    if conclusion.coverage_scope == COVERAGE_SCOPE_WHOLE_RUN:
        return "incomplete for the whole comparison - affected currency could not be established"
    if conclusion.coverage_scope == COVERAGE_SCOPE_CURRENCIES:
        return f"incomplete for {', '.join(conclusion.coverage_currencies)}"
    return "complete for every in-scope currency"


__all__ = [
    "CAUTION",
    "COVERAGE_SCOPE_BLOCKED",
    "COVERAGE_SCOPE_COMPLETE",
    "COVERAGE_SCOPE_CURRENCIES",
    "COVERAGE_SCOPE_WHOLE_RUN",
    "STATUS_BLOCKED",
    "STATUS_NO_REVIEW_ITEMS",
    "STATUS_REVIEW_REQUIRED",
    "Conclusion",
    "CurrencyResult",
    "build_conclusion",
    "coverage_scope_text",
]
