"""Deterministic sales↔JoFotara invoice matching (REC-001..004 slice).

Strategy (recorded in every fingerprint): exact (issuer, number) key match;
single-to-single comparison only (many-to-one never auto-matched); duplicates
clustered per side and excluded from matching; credit notes/reversals linked,
never netted; currency mismatch and credit-note overlap are review-required
ambiguities; missing values are insufficient data, never zero.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

from app.recon.contracts import (
    AMBIGUOUS,
    AMOUNT_MISMATCH,
    CREDIT_NOTE_LINKED,
    DUPLICATE_JOFOTARA,
    DUPLICATE_SALES,
    EXACT_MATCH,
    INSUFFICIENT_DATA,
    REVERSAL_NOTED,
    UNMATCHED_JOFOTARA,
    UNMATCHED_SALES,
    CanonicalInvoice,
    MatchOutcome,
    ReconcileRequest,
    ReconciliationReport,
    rule_for,
)


def _exact_delta(sales_amount: Decimal, jofo_amount: Decimal) -> Decimal:
    """Exact sales − JoFotara difference for any supported input length.

    Integer-scaled accumulation (align exponents, subtract exact ints) keeps
    arithmetic independent of the ambient decimal context, mirroring the
    FIN-CORE-01 exactness guarantee: no silent rounding for long inputs.
    """
    sales_tuple, jofo_tuple = sales_amount.as_tuple(), jofo_amount.as_tuple()
    sales_exp, jofo_exp = sales_tuple.exponent, jofo_tuple.exponent
    if isinstance(sales_exp, str) or isinstance(jofo_exp, str):
        raise ValueError("non-finite Decimal cannot be differenced")
    common = min(sales_exp, jofo_exp)
    sales_coeff = _coefficient(sales_tuple.digits, sales_tuple.sign) * (10 ** (sales_exp - common))
    jofo_coeff = _coefficient(jofo_tuple.digits, jofo_tuple.sign) * (10 ** (jofo_exp - common))
    coeff = sales_coeff - jofo_coeff
    if coeff == 0:
        return Decimal((0, (0,), common))
    sign = 0 if coeff > 0 else 1
    return Decimal((sign, tuple(int(d) for d in str(abs(coeff))), common))


def _coefficient(digits: tuple[int, ...], sign: int) -> int:
    value = int("".join(str(d) for d in digits) or "0")
    return -value if sign else value


def _period_flag(row_date: date | None, start: date | None, end: date | None) -> str:
    if row_date is None or (start is None and end is None):
        return "PERIOD_UNKNOWN"
    if (start is not None and row_date < start) or (end is not None and row_date > end):
        return "PERIOD_OUTSIDE"
    return "PERIOD_WITHIN"


def _missing_parts(row: CanonicalInvoice) -> tuple[str, ...]:
    missing: list[str] = []
    if not row.number.strip():
        missing.append("invoice_number")
    if row.amount is None:
        missing.append("amount")
    if row.currency is None:
        missing.append("currency")
    return tuple(missing)


def _sort_key(row: CanonicalInvoice) -> tuple[str, str, str]:
    issuer, number = row.key()
    return (issuer, number, row.amount_raw)


def reconcile(
    sales: tuple[CanonicalInvoice, ...],
    jofo: tuple[CanonicalInvoice, ...],
    request: ReconcileRequest,
) -> ReconciliationReport:
    """Match sales against JoFotara rows deterministically (pure function)."""
    if not isinstance(sales, tuple) or not isinstance(jofo, tuple):
        raise TypeError("sales and jofo must be tuples of CanonicalInvoice")
    for row in (*sales, *jofo):
        if not isinstance(row, CanonicalInvoice):
            raise TypeError(f"inputs must be CanonicalInvoice, got {type(row).__name__}")
    if not isinstance(request, ReconcileRequest):
        raise TypeError("request must be ReconcileRequest")

    outcomes: list[MatchOutcome] = []

    def emit(
        kind: str,
        sales_rows: tuple[CanonicalInvoice, ...] = (),
        jofo_rows: tuple[CanonicalInvoice, ...] = (),
        delta: Decimal | None = None,
        currency: str | None = None,
        rationale: tuple[str, ...] = (),
        flags: tuple[str, ...] = (),
    ) -> None:
        outcomes.append(
            MatchOutcome(
                kind=kind,
                rule=rule_for(kind, request.jurisdiction, request.rules_version),
                sales=sales_rows,
                jofo=jofo_rows,
                delta=delta,
                currency=currency,
                rationale=rationale,
                flags=flags,
            )
        )

    def period_flags(rows: tuple[CanonicalInvoice, ...]) -> tuple[str, ...]:
        positions = {_period_flag(r.transaction_date, request.period_start, request.period_end) for r in rows}
        positions.discard("PERIOD_WITHIN")
        return tuple(sorted(positions))

    # Stage 1: rows that cannot participate (missing key/amount/currency).
    sales_open: list[CanonicalInvoice] = []
    for row in sorted(sales, key=_sort_key):
        missing = _missing_parts(row)
        if missing:
            emit(
                INSUFFICIENT_DATA, sales_rows=(row,), rationale=tuple(f"MISSING_{m.upper()}" for m in missing)
            )
        else:
            sales_open.append(row)
    jofo_open: list[CanonicalInvoice] = []
    for row in sorted(jofo, key=_sort_key):
        missing = _missing_parts(row)
        if missing:
            emit(
                INSUFFICIENT_DATA, jofo_rows=(row,), rationale=tuple(f"MISSING_{m.upper()}" for m in missing)
            )
        else:
            jofo_open.append(row)

    # Stage 2: duplicate clusters per side (review-required, never matched).
    # Clusters are kind-aware: an invoice plus its credit note is a normal
    # business pattern (linked later), not a duplicate; two identical invoices
    # are. Kind classes: invoice, credit note, reversal.
    Grouped = dict[tuple[tuple[str, str], str], list[CanonicalInvoice]]

    def kind_class(row: CanonicalInvoice) -> str:
        if row.is_reversal:
            return "REVERSAL"
        if row.is_credit_note:
            return "CREDIT"
        return "INVOICE"

    def clusters(
        rows: list[CanonicalInvoice],
    ) -> tuple[Grouped, list[CanonicalInvoice]]:
        grouped: Grouped = {}
        for row in rows:
            grouped.setdefault((row.key(), kind_class(row)), []).append(row)
        singles = [group[0] for group in grouped.values() if len(group) == 1]
        dupes = {key: group for key, group in grouped.items() if len(group) > 1}
        return dupes, singles

    sales_dupes, sales_singles = clusters(sales_open)
    jofo_dupes, jofo_singles = clusters(jofo_open)
    for key in sorted(sales_dupes):
        emit(
            DUPLICATE_SALES,
            sales_rows=tuple(sales_dupes[key]),
            rationale=("DUPLICATE_KEY_SALES",),
            flags=period_flags(tuple(sales_dupes[key])),
        )
    for key in sorted(jofo_dupes):
        emit(
            DUPLICATE_JOFOTARA,
            jofo_rows=tuple(jofo_dupes[key]),
            rationale=("DUPLICATE_KEY_JOFOTARA",),
            flags=period_flags(tuple(jofo_dupes[key])),
        )

    # Stage 3: split credit notes / reversals from plain invoices (singles only;
    # duplicates were already emitted above and leave the matching pool).
    def split(
        rows: list[CanonicalInvoice],
    ) -> tuple[list[CanonicalInvoice], list[CanonicalInvoice], list[CanonicalInvoice]]:
        plain = [r for r in rows if not r.is_credit_note and not r.is_reversal]
        credits = [r for r in rows if r.is_credit_note and not r.is_reversal]
        reversals = [r for r in rows if r.is_reversal]
        return plain, credits, reversals

    sales_plain, sales_credits, sales_reversals = split(sales_singles)
    jofo_plain, jofo_credits, jofo_reversals = split(jofo_singles)

    # Stage 4: single-to-single exact-key matching (never many-to-one: every
    # key is unique on both sides here by construction).
    jofo_by_key = {row.key(): row for row in jofo_plain}
    matched_jofo_keys: set[tuple[str, str]] = set()
    credit_keys = {r.key() for r in (*sales_credits, *jofo_credits)}
    for row in sorted(sales_plain, key=_sort_key):
        counterpart = jofo_by_key.get(row.key())
        flags = period_flags((row,) + ((counterpart,) if counterpart else ()))
        if counterpart is None:
            emit(UNMATCHED_SALES, sales_rows=(row,), rationale=("MISSING_IN_JOFOTARA",), flags=flags)
            continue
        matched_jofo_keys.add(row.key())
        assert row.currency is not None and counterpart.currency is not None  # stage-1 guarantees
        if row.currency != counterpart.currency:
            emit(
                AMBIGUOUS,
                sales_rows=(row,),
                jofo_rows=(counterpart,),
                currency=None,
                rationale=("CURRENCY_MISMATCH",),
                flags=flags,
            )
            continue
        delta = _exact_delta(row.amount, counterpart.amount)  # type: ignore[arg-type]
        if abs(delta) <= request.tolerance:
            emit(
                EXACT_MATCH,
                sales_rows=(row,),
                jofo_rows=(counterpart,),
                delta=delta,
                currency=row.currency,
                rationale=("AMOUNTS_EQUAL",),
                flags=flags + (("WITHIN_TOLERANCE",) if delta != 0 else ()),
            )
        else:
            emit(
                AMOUNT_MISMATCH,
                sales_rows=(row,),
                jofo_rows=(counterpart,),
                delta=delta,
                currency=row.currency,
                rationale=("AMOUNT_DIFFERS",),
                flags=flags,
            )
        if row.key() in credit_keys:
            emit(
                AMBIGUOUS,
                sales_rows=(row,),
                jofo_rows=(counterpart,),
                delta=delta if row.currency == counterpart.currency else None,
                currency=row.currency if row.currency == counterpart.currency else None,
                rationale=("CREDIT_NOTE_OVERLAP",),
                flags=flags + ("REVIEW_ISSUER_AND_CREDIT",),
            )

    for row in sorted(jofo_plain, key=_sort_key):
        if row.key() not in matched_jofo_keys:
            emit(
                UNMATCHED_JOFOTARA,
                jofo_rows=(row,),
                rationale=("MISSING_IN_SALES",),
                flags=period_flags((row,)),
            )

    # Stage 5: credit notes and reversals link (never netted).
    invoice_keys = {r.key() for r in (*sales_plain, *jofo_plain)}
    for row in sorted((*sales_credits, *jofo_credits), key=_sort_key):
        linked = row.key() in invoice_keys
        emit(
            CREDIT_NOTE_LINKED,
            sales_rows=(row,) if row in sales_credits else (),
            jofo_rows=(row,) if row in jofo_credits else (),
            currency=row.currency,
            rationale=("CREDIT_NOTE_PRESERVED",),
            flags=period_flags((row,)) + (() if linked else ("UNLINKED",)),
        )
    for row in sorted((*sales_reversals, *jofo_reversals), key=_sort_key):
        linked = row.key() in invoice_keys
        emit(
            REVERSAL_NOTED,
            sales_rows=(row,) if row in sales_reversals else (),
            jofo_rows=(row,) if row in jofo_reversals else (),
            currency=row.currency,
            rationale=("REVERSAL_PRESERVED",),
            flags=period_flags((row,)) + (() if linked else ("UNLINKED",)),
        )

    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.kind] = counts.get(outcome.kind, 0) + 1
    return ReconciliationReport(
        tenant_id=request.tenant_id,
        sales_dataset_id=request.sales_dataset_id,
        jofo_dataset_id=request.jofo_dataset_id,
        jurisdiction=request.jurisdiction,
        rules_version=request.rules_version,
        tolerance=request.tolerance,
        period_start=request.period_start,
        period_end=request.period_end,
        outcomes=tuple(outcomes),
        counts=counts,
        sales_total=len(sales),
        jofo_total=len(jofo),
        fingerprint=_fingerprint(request, outcomes),
    )


def _fingerprint(request: ReconcileRequest, outcomes: list[MatchOutcome]) -> str:
    def invoice_blob(row: CanonicalInvoice) -> object:
        return [
            row.issuer,
            row.number,
            str(row.amount) if row.amount is not None else None,
            row.amount_raw,
            row.currency,
            row.transaction_date.isoformat() if row.transaction_date else None,
            row.is_credit_note,
            row.is_reversal,
            [
                row.provenance.dataset_id,
                row.provenance.source,
                row.provenance.row_number,
                row.provenance.raw_invoice,
            ]
            if row.provenance
            else None,
        ]

    def outcome_blob(outcome: MatchOutcome) -> object:
        return [
            outcome.kind,
            outcome.rule,
            [invoice_blob(r) for r in outcome.sales],
            [invoice_blob(r) for r in outcome.jofo],
            str(outcome.delta) if outcome.delta is not None else None,
            outcome.currency,
            list(outcome.rationale),
            list(outcome.flags),
        ]

    payload = {
        "tenant": request.tenant_id,
        "sales_dataset": request.sales_dataset_id,
        "jofo_dataset": request.jofo_dataset_id,
        "jurisdiction": request.jurisdiction,
        "rules": request.rules_version,
        "tolerance": str(request.tolerance),
        "period": [
            request.period_start.isoformat() if request.period_start else None,
            request.period_end.isoformat() if request.period_end else None,
        ],
        "outcomes": sorted(
            [outcome_blob(o) for o in outcomes], key=lambda blob: json.dumps(blob, sort_keys=True)
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
