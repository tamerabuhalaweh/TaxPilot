"""REC-SLICE-02 findings projection: ReconciliationReport -> review read model.

Pure deterministic transform from merged reconciliation outcomes (REC-001..004)
into accountant-facing review items. No persistence, no API, no decisions, no
report rendering — those arrive in later slices. Every input row is traceable
to a projected item (nothing dropped, nothing invented); amounts stay exact
Decimal (serialized as strings for machine-readable output); language is
factual (possible-issue phrasing only, never fraud or legal-violation claims).

Mapping policy v1 (versioned; hardcoded, caller-visible, revisable later):
- AMOUNT_MISMATCH / UNMATCHED_SALES / UNMATCHED_JOFOTARA -> discrepancy,
  HIGH, review required.
- DUPLICATE_SALES / DUPLICATE_JOFOTARA / AMBIGUOUS -> review candidate,
  MEDIUM, review required (possible duplicates are flagged, never asserted).
- INSUFFICIENT_DATA -> data quality, MEDIUM, review required (never zero).
- EXACT_MATCH / CREDIT_NOTE_LINKED / CREDIT_NOTE_UNVERIFIED / REVERSAL_NOTED
  / REVERSAL_UNVERIFIED -> informational, LOW, no review required. An exact
  match with flags (e.g. WITHIN_TOLERANCE, PERIOD_OUTSIDE) stays informational:
  the amounts reconcile, and the flags are preserved as context.
Unknown outcome kinds raise (fail closed) so new engine outcomes can never
silently pass through unmapped.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.recon.contracts import (
    AMBIGUOUS,
    AMOUNT_MISMATCH,
    CREDIT_NOTE_LINKED,
    CREDIT_NOTE_UNVERIFIED,
    DUPLICATE_JOFOTARA,
    DUPLICATE_SALES,
    EXACT_MATCH,
    INSUFFICIENT_DATA,
    REVERSAL_NOTED,
    REVERSAL_UNVERIFIED,
    UNMATCHED_JOFOTARA,
    UNMATCHED_SALES,
    CanonicalInvoice,
    ReconciliationReport,
)

PROJECTION_VERSION = "1"

CATEGORY_DIFFERENCE = "RECONCILIATION_DIFFERENCE"
CATEGORY_REVIEW = "REVIEW_CANDIDATE"
CATEGORY_QUALITY = "DATA_QUALITY"
CATEGORY_INFO = "INFORMATIONAL"

SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"

STATE_OPEN = "OPEN"

# kind -> (category, severity, review_required). Exhaustive over the engine
# contract; unknown kinds fail closed in project().
_POLICY: dict[str, tuple[str, str, bool]] = {
    AMOUNT_MISMATCH: (CATEGORY_DIFFERENCE, SEVERITY_HIGH, True),
    UNMATCHED_SALES: (CATEGORY_DIFFERENCE, SEVERITY_HIGH, True),
    UNMATCHED_JOFOTARA: (CATEGORY_DIFFERENCE, SEVERITY_HIGH, True),
    DUPLICATE_SALES: (CATEGORY_REVIEW, SEVERITY_MEDIUM, True),
    DUPLICATE_JOFOTARA: (CATEGORY_REVIEW, SEVERITY_MEDIUM, True),
    AMBIGUOUS: (CATEGORY_REVIEW, SEVERITY_MEDIUM, True),
    INSUFFICIENT_DATA: (CATEGORY_QUALITY, SEVERITY_MEDIUM, True),
    EXACT_MATCH: (CATEGORY_INFO, SEVERITY_LOW, False),
    CREDIT_NOTE_LINKED: (CATEGORY_INFO, SEVERITY_LOW, False),
    CREDIT_NOTE_UNVERIFIED: (CATEGORY_INFO, SEVERITY_LOW, False),
    REVERSAL_NOTED: (CATEGORY_INFO, SEVERITY_LOW, False),
    REVERSAL_UNVERIFIED: (CATEGORY_INFO, SEVERITY_LOW, False),
}


@dataclass(frozen=True)
class MoneyView:
    """Exact amount view (Decimal serialized as a plain string)."""

    amount: str
    currency: str


@dataclass(frozen=True)
class EvidenceRef:
    """Traceable pointer to one source row of a finding."""

    dataset_id: str
    source: str
    row_number: int
    raw_invoice: str
    role: str  # sales | jofo


@dataclass(frozen=True)
class ReviewFinding:
    """One accountant-facing review item (read model, no decisions attached)."""

    finding_id: str
    category: str
    severity: str
    state: str  # OPEN: lifecycle start; transitions arrive in a later slice
    review_required: bool
    rule: str
    outcome_kind: str
    title: str
    what: str
    compared: str
    difference: str
    why: str
    guidance: str
    sales: tuple[MoneyView | None, ...] = field(default_factory=tuple)
    jofo: tuple[MoneyView | None, ...] = field(default_factory=tuple)
    delta: str | None = None
    delta_currency: str | None = None
    evidence: tuple[EvidenceRef, ...] = field(default_factory=tuple)
    rationale: tuple[str, ...] = field(default_factory=tuple)
    flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FindingsReport:
    """Versioned, fingerprinted projection of one reconciliation run."""

    projection_version: str
    tenant_id: str
    sales_dataset_id: str
    jofo_dataset_id: str
    jurisdiction: str
    rules_version: str
    tolerance: Decimal
    period_start: date | None
    period_end: date | None
    recon_fingerprint: str
    findings: tuple[ReviewFinding, ...]
    summary: dict[str, object]
    fingerprint: str


def _money(row: CanonicalInvoice) -> MoneyView | None:
    if row.amount is None or row.currency is None:
        return None
    return MoneyView(amount=str(row.amount), currency=row.currency)


def _identity(row: CanonicalInvoice) -> str:
    return f"{row.issuer} / {row.number}"


def _describe(rows: tuple[CanonicalInvoice, ...]) -> str:
    return "; ".join(_identity(r) for r in rows) if rows else "—"


def _money_text(rows: tuple[CanonicalInvoice, ...]) -> str:
    parts = []
    for row in rows:
        view = _money(row)
        parts.append(
            f"{view.amount} {view.currency}" if view else "(amount unavailable)"
        )
    return "; ".join(parts) if parts else "—"


def _evidence(
    sales: tuple[CanonicalInvoice, ...], jofo: tuple[CanonicalInvoice, ...]
) -> tuple[EvidenceRef, ...]:
    refs: list[EvidenceRef] = []
    for row in sales:
        provenance = row.provenance
        refs.append(
            EvidenceRef(
                dataset_id=provenance.dataset_id if provenance else "",
                source=provenance.source if provenance else "",
                row_number=provenance.row_number if provenance else 0,
                raw_invoice=provenance.raw_invoice if provenance else row.number,
                role="sales",
            )
        )
    for row in jofo:
        provenance = row.provenance
        refs.append(
            EvidenceRef(
                dataset_id=provenance.dataset_id if provenance else "",
                source=provenance.source if provenance else "",
                row_number=provenance.row_number if provenance else 0,
                raw_invoice=provenance.raw_invoice if provenance else row.number,
                role="jofo",
            )
        )
    return tuple(refs)


def _texts(
    kind: str,
    sales: tuple[CanonicalInvoice, ...],
    jofo: tuple[CanonicalInvoice, ...],
    delta: Decimal | None,
    currency: str | None,
    rationale: tuple[str, ...],
    flags: tuple[str, ...],
) -> tuple[str, str, str, str, str, str, str | None]:
    """Return (title, what, compared, difference, why, guidance, delta_text)."""
    sales_text = _describe(sales)
    jofo_text = _describe(jofo)
    if kind == AMOUNT_MISMATCH:
        difference = (
            f"sales minus JoFotara = {delta} {currency} (exact)"
            if delta is not None and currency
            else "amounts differ (exact delta unavailable)"
        )
        return (
            f"Amount differs for {sales_text}",
            f"Sales invoice {sales_text} ({_money_text(sales)})",
            f"JoFotara invoice {jofo_text} ({_money_text(jofo)})",
            difference,
            "Both sides identify the same invoice but record different amounts.",
            "Compare the two source rows and confirm which amount is correct.",
            str(delta) if delta is not None else None,
        )
    if kind == UNMATCHED_SALES:
        return (
            f"Sales invoice without JoFotara counterpart: {sales_text}",
            f"Sales invoice {sales_text} ({_money_text(sales)})",
            "No JoFotara row with the same issuer and invoice number",
            f"Present in sales ({_money_text(sales)}); absent in JoFotara",
            "Presence is proven by the sales row; no counterpart was found.",
            "Check whether the JoFotara export is missing this invoice.",
            None,
        )
    if kind == UNMATCHED_JOFOTARA:
        return (
            f"JoFotara invoice without sales counterpart: {jofo_text}",
            f"JoFotara invoice {jofo_text} ({_money_text(jofo)})",
            "No sales row with the same issuer and invoice number",
            f"Present in JoFotara ({_money_text(jofo)}); absent in sales",
            "Presence is proven by the JoFotara row; no counterpart was found.",
            "Check whether the sales register is missing this invoice.",
            None,
        )
    if kind in (DUPLICATE_SALES, DUPLICATE_JOFOTARA):
        side = "sales" if kind == DUPLICATE_SALES else "JoFotara"
        rows = sales if kind == DUPLICATE_SALES else jofo
        return (
            f"Possible duplicate {side} rows for {_describe(rows)}",
            f"{len(rows)} {side} rows share the same issuer and invoice number",
            "Each other within the same dataset",
            "Same identity recorded more than once; counted once pending review",
            "Duplicate keys are flagged as possible duplicates, never asserted.",
            "Confirm whether these rows are repeated exports or distinct records.",
            None,
        )
    if kind == AMBIGUOUS:
        if "CURRENCY_MISMATCH" in rationale:
            difference = (
                f"currencies differ (sales {_money_text(sales)} vs "
                f"JoFotara {_money_text(jofo)}); no difference computed"
            )
            why = "Amounts across different currencies are never compared."
        elif "COMPARISON_INSUFFICIENT" in rationale:
            difference = "Comparison not possible; a value needed for comparison is missing"
            why = "Missing values are never treated as zero; the pair needs review."
        else:
            difference = "More than one row shares this identity; no automatic choice is made"
            why = "Duplicate counterparts prevent a unique match."
        return (
            f"Ambiguous match for {sales_text or jofo_text}",
            f"Sales: {sales_text} ({_money_text(sales)})",
            f"JoFotara: {jofo_text} ({_money_text(jofo)})",
            difference,
            why,
            "Resolve the ambiguity from the source rows, then re-run reconciliation.",
            None,
        )
    if kind == INSUFFICIENT_DATA:
        return (
            f"Insufficient data for {sales_text or jofo_text}",
            f"Row: {sales_text or jofo_text}",
            "Matching requirements (identity and values)",
            f"Missing: {', '.join(rationale) if rationale else 'required fields'}",
            "Rows lacking required fields are reported, never zero-filled.",
            "Complete the missing fields in the source and re-run normalization.",
            None,
        )
    if kind == EXACT_MATCH:
        difference = (
            f"Both sides record {_money_text(sales)}"
            + (" (within the configured tolerance)" if "WITHIN_TOLERANCE" in flags else "")
            + ("; recorded outside the selected period" if "PERIOD_OUTSIDE" in flags else "")
        )
        return (
            f"Reconciled: {sales_text}",
            f"Sales invoice {sales_text} ({_money_text(sales)})",
            f"JoFotara invoice {jofo_text} ({_money_text(jofo)})",
            difference,
            "Same identity and equal amounts (within tolerance where flagged).",
            "No action needed; kept for completeness and audit traceability.",
            str(delta) if delta is not None else None,
        )
    if kind in (CREDIT_NOTE_LINKED, CREDIT_NOTE_UNVERIFIED, REVERSAL_NOTED, REVERSAL_UNVERIFIED):
        noun = "Credit note" if "CREDIT" in kind else "Reversal"
        linked = "linked to its original document" if "LINKED" in kind or "NOTED" in kind else (
            "kept as relationship-unverified; no link is asserted"
        )
        return (
            f"{noun} preserved: {sales_text or jofo_text}",
            f"{noun} {sales_text or jofo_text} ({_money_text(sales or jofo)})",
            "Original-document reference where stated",
            f"{noun} {linked}; amounts are not netted",
            "Credit notes and reversals are linked records, never netted.",
            "No action needed unless the underlying invoice is under review.",
            None,
        )
    raise ValueError(f"unmapped outcome kind: {kind!r}")  # pragma: no cover


def project(report: ReconciliationReport) -> FindingsReport:
    """Project one reconciliation report into review findings (pure function)."""
    if not isinstance(report, ReconciliationReport):
        raise TypeError(
            f"report must be ReconciliationReport, got {type(report).__name__}"
        )
    findings: list[ReviewFinding] = []
    for index, outcome in enumerate(report.outcomes):
        try:
            category, severity, review_required = _POLICY[outcome.kind]
        except KeyError:
            raise ValueError(f"unmapped outcome kind: {outcome.kind!r}") from None
        title, what, compared, difference, why, guidance, delta_text = _texts(
            outcome.kind,
            outcome.sales,
            outcome.jofo,
            outcome.delta,
            outcome.currency,
            outcome.rationale,
            outcome.flags,
        )
        findings.append(
            ReviewFinding(
                finding_id=f"{report.fingerprint[:12]}-{index:04d}",
                category=category,
                severity=severity,
                state=STATE_OPEN,
                review_required=review_required,
                rule=outcome.rule,
                outcome_kind=outcome.kind,
                title=title,
                what=what,
                compared=compared,
                difference=difference,
                why=why,
                guidance=guidance,
                sales=tuple(_money(r) for r in outcome.sales),
                jofo=tuple(_money(r) for r in outcome.jofo),
                delta=delta_text,
                delta_currency=outcome.currency,
                evidence=_evidence(outcome.sales, outcome.jofo),
                rationale=outcome.rationale,
                flags=outcome.flags,
            )
        )
    by_category: dict[str, int] = {}
    for item in findings:
        by_category[item.category] = by_category.get(item.category, 0) + 1
    summary: dict[str, object] = {
        "total": len(findings),
        "review_required": sum(1 for item in findings if item.review_required),
        "informational": sum(1 for item in findings if not item.review_required),
        "by_category": by_category,
        "by_outcome_kind": dict(report.counts),
    }
    return FindingsReport(
        projection_version=PROJECTION_VERSION,
        tenant_id=report.tenant_id,
        sales_dataset_id=report.sales_dataset_id,
        jofo_dataset_id=report.jofo_dataset_id,
        jurisdiction=report.jurisdiction,
        rules_version=report.rules_version,
        tolerance=report.tolerance,
        period_start=report.period_start,
        period_end=report.period_end,
        recon_fingerprint=report.fingerprint,
        findings=tuple(findings),
        summary=summary,
        fingerprint=_fingerprint(report, tuple(findings)),
    )


def _fingerprint(report: ReconciliationReport, findings: tuple[ReviewFinding, ...]) -> str:
    def finding_blob(item: ReviewFinding) -> object:
        return [
            item.finding_id,
            item.category,
            item.severity,
            item.state,
            item.review_required,
            item.rule,
            item.outcome_kind,
            item.title,
            item.what,
            item.compared,
            item.difference,
            item.why,
            item.guidance,
            [[m.amount if m else None, m.currency if m else None] for m in item.sales],
            [[m.amount if m else None, m.currency if m else None] for m in item.jofo],
            item.delta,
            item.delta_currency,
            [
                [e.dataset_id, e.source, e.row_number, e.raw_invoice, e.role]
                for e in item.evidence
            ],
            list(item.rationale),
            list(item.flags),
        ]

    payload = {
        "projection": PROJECTION_VERSION,
        "recon": report.fingerprint,
        "tenant": report.tenant_id,
        "sales_dataset": report.sales_dataset_id,
        "jofo_dataset": report.jofo_dataset_id,
        "jurisdiction": report.jurisdiction,
        "rules": report.rules_version,
        "tolerance": str(report.tolerance),
        "period": [
            report.period_start.isoformat() if report.period_start else None,
            report.period_end.isoformat() if report.period_end else None,
        ],
        "findings": [finding_blob(item) for item in findings],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
