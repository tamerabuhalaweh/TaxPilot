"""Plain-language result summary shared by the demo API and both exports.

The engine returns exact decimals and code-shaped metadata; accountants need a
short, honest read of *what the run concluded* without turning the UI into a
second calculation. This module derives presentation-only facts from the
already-computed findings:

- an overall status that never asserts more than the engine proved;
- per-currency totals only when the engine produced a DIFFERENCE outcome;
- the affected currencies and reasons when coverage was incomplete.

Nothing here changes a verdict, an amount, or a fingerprint. Equal totals are
explicitly not treated as proof of completeness.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.recon.gl import GLComparisonReport, GLFinding, GLFindingsReport
from app.recon.gl.contracts import DIFFERENCE, INCONCLUSIVE_COVERAGE

STATUS_BLOCKED = "BLOCKED"
STATUS_REVIEW_REQUIRED = "REVIEW_REQUIRED"
STATUS_NO_REVIEW_ITEMS = "NO_REVIEW_ITEMS"

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
    """One currency that received an explicit (non-informational) outcome."""

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

    @property
    def coverage_complete(self) -> bool:
        return not self.coverage_currencies


def _amount(views: tuple[object, ...]) -> str | None:
    if not views:
        return None
    amount = getattr(views[0], "amount", None)
    return str(amount) if amount is not None else None


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
    difference = [item for item in findings.findings if item.outcome_kind == DIFFERENCE]
    coverage = [item for item in findings.findings if item.outcome_kind == INCONCLUSIVE_COVERAGE]

    currency_results: list[CurrencyResult] = []
    for item in difference:
        if item.delta_currency is None:
            continue
        currency_results.append(
            CurrencyResult(
                currency=item.delta_currency,
                outcome=DIFFERENCE,
                sales_total=_amount(item.sales),
                gl_total=_amount(item.gl),
                delta=item.delta,
            )
        )
    for item in coverage:
        if item.delta_currency is None:
            continue
        currency_results.append(
            CurrencyResult(
                currency=item.delta_currency,
                outcome=INCONCLUSIVE_COVERAGE,
                sales_total=None,
                gl_total=None,
                delta=None,
            )
        )

    coverage_currencies = tuple(
        dict.fromkeys(item.currency for item in currency_results if item.outcome == INCONCLUSIVE_COVERAGE)
    )
    coverage_reasons = tuple(report.inconclusive_reasons)
    coverage_explanations = tuple(_explain(reason) for reason in coverage_reasons)
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
        if currency_results:
            differing = [item.currency for item in currency_results if item.outcome == DIFFERENCE]
            if differing:
                noun = "currency differs" if len(differing) == 1 else "currencies differ"
                parts.append(f"{len(differing)} {noun} beyond tolerance: {', '.join(differing)}.")
        if coverage_currencies:
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
        currency_results=tuple(currency_results),
        coverage_currencies=coverage_currencies,
        coverage_reasons=coverage_reasons,
        coverage_explanations=coverage_explanations,
    )


__all__ = [
    "CAUTION",
    "STATUS_BLOCKED",
    "STATUS_NO_REVIEW_ITEMS",
    "STATUS_REVIEW_REQUIRED",
    "Conclusion",
    "CurrencyResult",
    "build_conclusion",
]
