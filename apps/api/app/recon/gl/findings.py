"""REC-005 findings projection: GLComparisonReport -> review read model.

Pure deterministic transform of Sales<->GL outcomes into accountant-facing
review items. No persistence, API, decisions, or rendering. Every outcome maps
to exactly one item (unknown kinds fail closed); amounts stay exact Decimal
(serialized as strings); language is factual (possible-issue phrasing, never a
fraud/tax/legal conclusion). A blocked run (default-deny) yields one review
item that states the reconciliation did not run and why.

Mapping policy v1 (versioned; hardcoded, caller-visible, revisable later):
- DIFFERENCE / MISSING_GL -> discrepancy, HIGH, review required.
- MISSING_SALES / DUPLICATE_GL / DUPLICATE_SALES -> review candidate, MEDIUM,
  review required.
- INVALID_DEBIT_CREDIT_PAIR / MISSING_VALUE / PERIOD_OUTSIDE / PERIOD_UNKNOWN /
  CURRENCY_NOT_IN_SCOPE -> data quality, MEDIUM, review required.
- REVERSAL_UNVERIFIED / CREDIT_NOTE_UNVERIFIED -> relationship verification,
  MEDIUM (data quality when a reference is entirely absent), review required.
- RECONCILED / REVERSAL_NOTED / CREDIT_NOTE_LINKED -> informational, LOW, no
  review required.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal

from app.recon.findings import MoneyView
from app.recon.gl.contracts import (
    CREDIT_NOTE_LINKED,
    CREDIT_NOTE_UNVERIFIED,
    CURRENCY_NOT_IN_SCOPE,
    DIFFERENCE,
    DUPLICATE_GL,
    DUPLICATE_SALES,
    INVALID_DEBIT_CREDIT_PAIR,
    MISSING_GL,
    MISSING_SALES,
    MISSING_VALUE,
    PERIOD_OUTSIDE,
    PERIOD_UNKNOWN,
    RECONCILED,
    REVERSAL_NOTED,
    REVERSAL_UNVERIFIED,
    GLComparisonReport,
    GLLine,
    GLOutcome,
    SalesRegisterEntry,
)

GL_PROJECTION_VERSION = "1"

CATEGORY_DIFFERENCE = "RECONCILIATION_DIFFERENCE"
CATEGORY_REVIEW = "REVIEW_CANDIDATE"
CATEGORY_QUALITY = "DATA_QUALITY"
CATEGORY_INFO = "INFORMATIONAL"
CATEGORY_CONTRACT = "INSUFFICIENT_CONTRACT"

SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"

REVIEW_PENDING = "PENDING_REVIEW"

BLOCKED_KIND = "BLOCKED"

_POLICY: dict[str, tuple[str, str, bool]] = {
    DIFFERENCE: (CATEGORY_DIFFERENCE, SEVERITY_HIGH, True),
    MISSING_GL: (CATEGORY_DIFFERENCE, SEVERITY_HIGH, True),
    MISSING_SALES: (CATEGORY_REVIEW, SEVERITY_MEDIUM, True),
    DUPLICATE_GL: (CATEGORY_REVIEW, SEVERITY_MEDIUM, True),
    DUPLICATE_SALES: (CATEGORY_REVIEW, SEVERITY_MEDIUM, True),
    INVALID_DEBIT_CREDIT_PAIR: (CATEGORY_QUALITY, SEVERITY_MEDIUM, True),
    MISSING_VALUE: (CATEGORY_QUALITY, SEVERITY_MEDIUM, True),
    PERIOD_OUTSIDE: (CATEGORY_QUALITY, SEVERITY_MEDIUM, True),
    PERIOD_UNKNOWN: (CATEGORY_QUALITY, SEVERITY_MEDIUM, True),
    CURRENCY_NOT_IN_SCOPE: (CATEGORY_QUALITY, SEVERITY_MEDIUM, True),
    REVERSAL_UNVERIFIED: (CATEGORY_REVIEW, SEVERITY_MEDIUM, True),
    CREDIT_NOTE_UNVERIFIED: (CATEGORY_REVIEW, SEVERITY_MEDIUM, True),
    RECONCILED: (CATEGORY_INFO, SEVERITY_LOW, False),
    REVERSAL_NOTED: (CATEGORY_INFO, SEVERITY_LOW, False),
    CREDIT_NOTE_LINKED: (CATEGORY_INFO, SEVERITY_LOW, False),
}


def _policy_for(kind: str, flags: tuple[str, ...]) -> tuple[str, str, bool]:
    try:
        category, severity, review_required = _POLICY[kind]
    except KeyError:
        raise ValueError(f"unmapped GL outcome kind: {kind!r}") from None
    if kind in (REVERSAL_UNVERIFIED, CREDIT_NOTE_UNVERIFIED) and "NO_REFERENCE" in flags:
        category = CATEGORY_QUALITY
    return category, severity, review_required


@dataclass(frozen=True)
class GLEvidenceRef:
    """Traceable pointer to one source row of a GL finding (role sales|gl)."""

    dataset_id: str
    source: str
    row_number: int
    raw_reference: str
    role: str


@dataclass(frozen=True)
class GLFinding:
    """One accountant-facing Sales<->GL review item (read model, no decisions)."""

    finding_id: str
    category: str
    severity: str
    review_state: str | None
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
    gl: tuple[MoneyView | None, ...] = field(default_factory=tuple)
    delta: str | None = None
    delta_currency: str | None = None
    evidence: tuple[GLEvidenceRef, ...] = field(default_factory=tuple)
    rationale: tuple[str, ...] = field(default_factory=tuple)
    flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GLFindingsReport:
    """Versioned, fingerprinted projection of one REC-005 run."""

    projection_version: str
    tenant_id: str
    client_id: str
    sales_dataset_id: str
    gl_dataset_id: str
    jurisdiction: str
    rules_version: str
    blocked: bool
    block_reasons: tuple[str, ...]
    recon_fingerprint: str
    findings: tuple[GLFinding, ...]
    summary: dict[str, object]
    fingerprint: str


def _money(amount: Decimal | None, currency: str | None) -> MoneyView | None:
    if amount is None or currency is None:
        return None
    return MoneyView(amount=str(amount), currency=currency)


def _gl_identity(line: GLLine) -> str:
    return f"{line.journal_id} / line {line.line_number} [{line.account_code}]"


def _sales_identity(entry: SalesRegisterEntry) -> str:
    return f"{entry.issuer} / {entry.invoice_number}"


def _describe_gl(rows: tuple[GLLine, ...]) -> str:
    return "; ".join(_gl_identity(r) for r in rows) if rows else "—"


def _describe_sales(rows: tuple[SalesRegisterEntry, ...]) -> str:
    return "; ".join(_sales_identity(r) for r in rows) if rows else "—"


def _evidence(gl: tuple[GLLine, ...], sales: tuple[SalesRegisterEntry, ...]) -> tuple[GLEvidenceRef, ...]:
    """Build evidence refs, failing closed on unusable provenance."""
    refs: list[GLEvidenceRef] = []
    for line in gl:
        provenance = line.provenance
        row_number = provenance.row_number if provenance else None
        if (
            provenance is None
            or not provenance.dataset_id.strip()
            or not provenance.source.strip()
            or isinstance(row_number, bool)
            or not isinstance(row_number, int)
            or row_number <= 0
        ):
            raise ValueError(
                f"missing evidence provenance for GL line {line.journal_id!r}/"
                f"{line.line_number}: findings require dataset_id + source + a "
                "positive integer row_number"
            )
        refs.append(
            GLEvidenceRef(
                dataset_id=provenance.dataset_id,
                source=provenance.source,
                row_number=provenance.row_number,
                raw_reference=provenance.raw_reference,
                role="gl",
            )
        )
    for entry in sales:
        sales_provenance = entry.provenance
        sales_row_number = sales_provenance.row_number if sales_provenance else None
        if (
            sales_provenance is None
            or not sales_provenance.dataset_id.strip()
            or not sales_provenance.source.strip()
            or isinstance(sales_row_number, bool)
            or not isinstance(sales_row_number, int)
            or sales_row_number <= 0
        ):
            raise ValueError(
                f"missing evidence provenance for sales row "
                f"{entry.issuer!r} / {entry.invoice_number!r}: findings require "
                "dataset_id + source + a positive integer row_number"
            )
        refs.append(
            GLEvidenceRef(
                dataset_id=sales_provenance.dataset_id,
                source=sales_provenance.source,
                row_number=sales_provenance.row_number,
                raw_reference=sales_provenance.raw_invoice,
                role="sales",
            )
        )
    return tuple(refs)


def _texts(outcome: GLOutcome) -> tuple[str, str, str, str, str, str, str | None]:
    """Return (title, what, compared, difference, why, guidance, delta_text)."""
    gl_text = _describe_gl(outcome.gl)
    sales_text = _describe_sales(outcome.sales)
    currency = outcome.currency or ""
    if outcome.kind == DIFFERENCE:
        return (
            f"Sales and GL totals differ ({currency})",
            f"Sales total {outcome.sales_total} vs GL total {outcome.gl_total} {currency}",
            "Sales-register measure total vs in-scope GL posting total",
            f"sales minus GL = {outcome.delta} {currency} (exact, beyond tolerance)",
            "The approved policy's account scope and convention were applied; the totals do not agree.",
            "Review the in-scope GL postings and sales rows for this currency and period.",
            str(outcome.delta) if outcome.delta is not None else None,
        )
    if outcome.kind == RECONCILED:
        return (
            f"Sales and GL reconcile ({currency})",
            f"Sales total {outcome.sales_total} vs GL total {outcome.gl_total} {currency}",
            "Sales-register measure total vs in-scope GL posting total",
            "Both sides agree within the approved tolerance",
            "Totals agree under the approved policy (exact Decimals).",
            "No action needed; kept for completeness and audit traceability.",
            str(outcome.delta) if outcome.delta is not None else None,
        )
    if outcome.kind == MISSING_GL:
        return (
            f"Sales total without in-scope GL posting ({currency})",
            f"Sales rows: {sales_text}",
            "In-scope GL postings for this currency/period",
            "Sales activity exists but no in-scope GL posting was found",
            "Coverage may be incomplete; this is not an assertion about the books.",
            "Confirm the GL was included/mapped for this currency and period, then re-run.",
            None,
        )
    if outcome.kind == MISSING_SALES:
        return (
            f"GL posting without sales counterpart ({currency})",
            f"GL rows: {gl_text}",
            "Sales-register rows for this currency/period",
            "In-scope GL activity exists but no sales rows were found",
            "Coverage may be incomplete; a possible posting/period mismatch.",
            "Confirm whether the sales register is complete for this currency and period.",
            None,
        )
    if outcome.kind in (DUPLICATE_GL, DUPLICATE_SALES):
        side = "GL journal line" if outcome.kind == DUPLICATE_GL else "sales invoice"
        rows = outcome.gl if outcome.kind == DUPLICATE_GL else outcome.sales
        return (
            f"Possible duplicate {side} rows",
            f"{len(rows)} rows share the same identity",
            "Each other within the same dataset",
            "Duplicate identities are reported and excluded from the aggregate; "
            "no automatic choice is made and no verdict was produced for the affected currency",
            "Duplicates are flagged as possible, never asserted.",
            "Confirm whether these are repeated exports or distinct records, then re-run.",
            None,
        )
    if outcome.kind == INVALID_DEBIT_CREDIT_PAIR:
        return (
            "Invalid debit/credit pair on GL line",
            f"GL line {gl_text}",
            "Debit and credit columns",
            "Both a debit and a credit are populated; the line was excluded from totals",
            "Ambiguous debit/credit pairs are reported, never netted or guessed.",
            "Correct the source line so exactly one of debit/credit is set, then re-run.",
            None,
        )
    if outcome.kind == MISSING_VALUE:
        missing = ", ".join(outcome.rationale) if outcome.rationale else "required value"
        subject = gl_text if outcome.gl else sales_text
        return (
            f"Insufficient data for {subject}",
            f"Row: {subject}",
            "A value required for comparison",
            f"Missing: {missing}",
            "Missing values are never treated as zero.",
            "Complete the missing fields in the source and re-run normalization.",
            None,
        )
    if outcome.kind == CURRENCY_NOT_IN_SCOPE:
        return (
            f"Currency {outcome.currency} is outside the approved scope",
            f"Row(s) in currency {outcome.currency}",
            "Approved currency scope",
            "The row's currency is not approved for comparison; it was excluded and never converted",
            "Currencies are never combined and no FX is applied.",
            "Approve a currency policy for this currency if it should participate, then re-run.",
            None,
        )
    if outcome.kind in (PERIOD_OUTSIDE, PERIOD_UNKNOWN):
        note = (
            "recorded outside the requested period"
            if outcome.kind == PERIOD_OUTSIDE
            else "has no transaction date, so period placement cannot be confirmed"
        )
        return (
            "Period placement needs review",
            f"Row(s): {gl_text if outcome.gl else sales_text}",
            "Requested reconciliation period",
            f"The row {note}; it was excluded from the period totals",
            "Timing/period differences are surfaced, never silently netted.",
            "Confirm the period selection or the source date, then re-run reconciliation.",
            None,
        )
    if outcome.kind in (REVERSAL_NOTED, CREDIT_NOTE_LINKED):
        noun = "Reversal" if outcome.kind == REVERSAL_NOTED else "Credit note"
        return (
            f"{noun} preserved",
            f"{noun}: {gl_text if outcome.gl else sales_text}",
            "Original-document reference where stated",
            f"{noun} linked to its original document; amounts are not netted",
            "Reversals and credit notes are linked records, never netted.",
            "No action needed unless the underlying document is under review.",
            None,
        )
    if outcome.kind in (REVERSAL_UNVERIFIED, CREDIT_NOTE_UNVERIFIED):
        noun = "Reversal" if outcome.kind == REVERSAL_UNVERIFIED else "Credit note"
        if "NO_REFERENCE" in outcome.flags:
            difference = f"{noun} states no original-document reference; no link is asserted"
        else:
            difference = f"{noun} reference names no existing document; no link is asserted"
        return (
            f"{noun} relationship needs verification",
            f"{noun}: {gl_text if outcome.gl else sales_text}",
            "Original-document reference where stated",
            f"{difference}; amounts are not netted",
            "Reversals and credit notes link only through an explicit reference.",
            "Establish which original document this relates to, then re-run reconciliation.",
            None,
        )
    raise ValueError(f"unmapped GL outcome kind: {outcome.kind!r}")  # pragma: no cover


def _blocked_finding(report: GLComparisonReport, index: int) -> GLFinding:
    reasons = ", ".join(report.block_reasons) if report.block_reasons else "insufficient contract"
    return GLFinding(
        finding_id=f"{report.fingerprint[:12]}-{index:04d}",
        category=CATEGORY_CONTRACT,
        severity=SEVERITY_HIGH,
        review_state=REVIEW_PENDING,
        review_required=True,
        rule=f"{report.jurisdiction}/REC-005/{report.rules_version}",
        outcome_kind=BLOCKED_KIND,
        title="Sales/GL reconciliation not run (insufficient approved contract)",
        what="No approved GL comparison policy was supplied for this run",
        compared="Approved comparison policy (basis, account scope, measures, convention, currencies)",
        difference=f"Reconciliation refused: {reasons}",
        why="The engine is default-deny: without an approved accounting policy it never "
        "invents a scope, measure, sign convention, or FX rule.",
        guidance="Obtain an approved comparison policy (account scope + sales measure + "
        "debit/credit convention + currency scope) and re-run; see the REC-GL-01 boundary doc.",
        rationale=report.block_reasons,
    )


def project_gl(report: GLComparisonReport) -> GLFindingsReport:
    """Project one REC-005 report into review findings (pure function)."""
    if not isinstance(report, GLComparisonReport):
        raise TypeError(f"report must be GLComparisonReport, got {type(report).__name__}")
    findings: list[GLFinding] = []
    if report.blocked:
        findings.append(_blocked_finding(report, 0))
    else:
        for index, outcome in enumerate(report.outcomes):
            category, severity, review_required = _policy_for(outcome.kind, outcome.flags)
            title, what, compared, difference, why, guidance, delta_text = _texts(outcome)
            if outcome.sales_total is not None or outcome.gl_total is not None:
                sales_views: tuple[MoneyView | None, ...] = (
                    (_money(outcome.sales_total, outcome.currency),)
                    if outcome.sales_total is not None
                    else ()
                )
                gl_views: tuple[MoneyView | None, ...] = (
                    (_money(outcome.gl_total, outcome.currency),) if outcome.gl_total is not None else ()
                )
            else:
                measure = report.sales_measure
                sales_views = tuple(
                    _money(_selected_measure(entry, measure), entry.currency) for entry in outcome.sales
                )
                gl_views = tuple(_money(_signed_or_none(line), line.currency) for line in outcome.gl)
            findings.append(
                GLFinding(
                    finding_id=f"{report.fingerprint[:12]}-{index:04d}",
                    category=category,
                    severity=severity,
                    review_state=REVIEW_PENDING if review_required else None,
                    review_required=review_required,
                    rule=outcome.rule,
                    outcome_kind=outcome.kind,
                    title=title,
                    what=what,
                    compared=compared,
                    difference=difference,
                    why=why,
                    guidance=guidance,
                    sales=sales_views,
                    gl=gl_views,
                    delta=delta_text,
                    delta_currency=outcome.currency,
                    evidence=_evidence(outcome.gl, outcome.sales),
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
        "blocked": report.blocked,
        "block_reasons": list(report.block_reasons),
    }
    return GLFindingsReport(
        projection_version=GL_PROJECTION_VERSION,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        sales_dataset_id=report.sales_dataset_id,
        gl_dataset_id=report.gl_dataset_id,
        jurisdiction=report.jurisdiction,
        rules_version=report.rules_version,
        blocked=report.blocked,
        block_reasons=report.block_reasons,
        recon_fingerprint=report.fingerprint,
        findings=tuple(findings),
        summary=summary,
        fingerprint=_fingerprint(report, tuple(findings)),
    )


def _selected_measure(entry: SalesRegisterEntry, measure: str | None) -> Decimal | None:
    if measure is None:
        return None
    amount, _raw = entry.measure(measure)
    return amount


def _signed_or_none(line: GLLine) -> Decimal | None:
    """A per-line display amount that never silently nets a debit/credit pair."""
    if line.debit is not None and line.credit is None:
        return line.debit
    if line.credit is not None and line.debit is None:
        return line.credit
    return None


def _fingerprint(report: GLComparisonReport, findings: tuple[GLFinding, ...]) -> str:
    def finding_blob(item: GLFinding) -> object:
        return [
            item.finding_id,
            item.category,
            item.severity,
            item.review_state,
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
            [[m.amount if m else None, m.currency if m else None] for m in item.gl],
            item.delta,
            item.delta_currency,
            [[e.dataset_id, e.source, e.row_number, e.raw_reference, e.role] for e in item.evidence],
            list(item.rationale),
            list(item.flags),
        ]

    payload = {
        "projection": GL_PROJECTION_VERSION,
        "recon": report.fingerprint,
        "tenant": report.tenant_id,
        "client": report.client_id,
        "sales_dataset": report.sales_dataset_id,
        "gl_dataset": report.gl_dataset_id,
        "jurisdiction": report.jurisdiction,
        "rules": report.rules_version,
        "findings": [finding_blob(item) for item in findings],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "GL_PROJECTION_VERSION",
    "GLFinding",
    "GLFindingsReport",
    "project_gl",
]
