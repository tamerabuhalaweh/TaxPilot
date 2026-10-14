"""Deterministic sales↔JoFotara invoice matching (REC-001..004 slice).

Strategy (recorded in every fingerprint): presence is matched on exact
(issuer, number) keys first — a row with a valid key but missing amount or
currency still proves presence; only the comparison is then insufficient
(review-required), never reported as absence. Duplicates cluster per side and
kind; their counterparts on the other side become ambiguous links, never false
unmatched findings. Single-to-single comparison only (many-to-one never
auto-matched). Credit notes and reversals link ONLY through an explicit
original-document reference naming an existing invoice; otherwise they are
preserved as relationship-unverified. Missing keys are insufficient data;
missing values are never zero. All ordering is total (keys, values, flags,
provenance), so fingerprints are stable under any input permutation.
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


def _sort_key(
    row: CanonicalInvoice,
) -> tuple[str, str, str, str, str, str, str, str, bool, bool, str, str, str, int, str]:
    """Total order over identity, values, flags, and provenance.

    The normalized key comes first (matching semantics unchanged); RAW issuer
    and RAW number follow as tie-breakers because the fingerprint serializes
    raw values — equal sort keys therefore imply identical serialized
    evidence, and no input permutation can move the fingerprint.
    """
    issuer, number = row.key()
    provenance = row.provenance
    return (
        issuer,
        number,
        row.issuer,
        row.number,
        row.amount_raw,
        str(row.amount) if row.amount is not None else "",
        row.currency or "",
        row.transaction_date.isoformat() if row.transaction_date else "",
        row.is_credit_note,
        row.is_reversal,
        row.reference_number or "",
        provenance.dataset_id if provenance else "",
        provenance.source if provenance else "",
        provenance.row_number if provenance else 0,
        provenance.raw_invoice if provenance else "",
    )


def _key_missing(row: CanonicalInvoice) -> tuple[str, ...]:
    missing: list[str] = []
    if not row.number.strip():
        missing.append("invoice_number")
    if not row.issuer.strip():
        missing.append("issuer")
    return tuple(f"MISSING_{m.upper()}" for m in missing)


def _value_missing(row: CanonicalInvoice) -> tuple[str, ...]:
    missing: list[str] = []
    if row.amount is None:
        missing.append("MISSING_AMOUNT")
    if row.currency is None:
        missing.append("MISSING_CURRENCY")
    return tuple(missing)


def _kind_class(row: CanonicalInvoice) -> str:
    if row.is_reversal:
        return "REVERSAL"
    if row.is_credit_note:
        return "CREDIT"
    return "INVOICE"


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
                sales=tuple(sorted(sales_rows, key=_sort_key)),
                jofo=tuple(sorted(jofo_rows, key=_sort_key)),
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

    # Stage 1: rows without an identity key cannot be placed anywhere.
    sales_keyed: list[CanonicalInvoice] = []
    for row in sorted(sales, key=_sort_key):
        missing = _key_missing(row)
        if missing:
            emit(INSUFFICIENT_DATA, sales_rows=(row,), rationale=missing)
        else:
            sales_keyed.append(row)
    jofo_keyed: list[CanonicalInvoice] = []
    for row in sorted(jofo, key=_sort_key):
        missing = _key_missing(row)
        if missing:
            emit(INSUFFICIENT_DATA, jofo_rows=(row,), rationale=missing)
        else:
            jofo_keyed.append(row)

    # Stage 2: duplicate clusters per side and kind (review-required; their
    # members leave the matching pool, but their counterparts do NOT become
    # unmatched — see stage 2b).
    Grouped = dict[tuple[tuple[str, str], str], list[CanonicalInvoice]]

    def clusters(
        rows: list[CanonicalInvoice],
    ) -> tuple[Grouped, list[CanonicalInvoice]]:
        grouped: Grouped = {}
        for row in rows:
            grouped.setdefault((row.key(), _kind_class(row)), []).append(row)
        singles = [group[0] for group in grouped.values() if len(group) == 1]
        dupes = {key: group for key, group in grouped.items() if len(group) > 1}
        return dupes, singles

    sales_dupes, sales_singles = clusters(sales_keyed)
    jofo_dupes, jofo_singles = clusters(jofo_keyed)
    for cluster_key in sorted(sales_dupes):
        members = sales_dupes[cluster_key]
        emit(
            DUPLICATE_SALES,
            sales_rows=tuple(members),
            rationale=("DUPLICATE_KEY_SALES",),
            flags=period_flags(tuple(members)),
        )
    for cluster_key in sorted(jofo_dupes):
        members = jofo_dupes[cluster_key]
        emit(
            DUPLICATE_JOFOTARA,
            jofo_rows=tuple(members),
            rationale=("DUPLICATE_KEY_JOFOTARA",),
            flags=period_flags(tuple(members)),
        )

    # Stage 2b: duplicate counterparts are ambiguous, never unmatched. Only
    # rows sharing the duplicated (key, kind-class) prove presence on the other
    # side; rows of other kinds proceed to normal matching.
    sales_consumed: set[int] = set()
    jofo_consumed: set[int] = set()
    sales_positions = {id(row): index for index, row in enumerate(sales_singles)}
    jofo_positions = {id(row): index for index, row in enumerate(jofo_singles)}

    def same_kind_counterparts(
        rows: list[CanonicalInvoice], key: tuple[str, str], kind: str
    ) -> list[CanonicalInvoice]:
        return [r for r in rows if r.key() == key and _kind_class(r) == kind]

    for cluster_key in sorted(set(sales_dupes) | set(jofo_dupes)):
        key, kind = cluster_key
        sales_members = sales_dupes.get(cluster_key, [])
        jofo_members = jofo_dupes.get(cluster_key, [])
        sales_others = same_kind_counterparts(sales_singles, key, kind)
        jofo_others = same_kind_counterparts(jofo_singles, key, kind)
        if not sales_others and not jofo_others and not (sales_members and jofo_members):
            continue  # cluster stands alone; nothing proven present elsewhere
        emit(
            AMBIGUOUS,
            sales_rows=tuple(sales_members + sales_others),
            jofo_rows=tuple(jofo_members + jofo_others),
            rationale=("DUPLICATE_COUNTERPART",),
            flags=period_flags(tuple(sales_members + sales_others + jofo_members + jofo_others)),
        )
        for row in sales_others:
            sales_consumed.add(sales_positions[id(row)])
        for row in jofo_others:
            jofo_consumed.add(jofo_positions[id(row)])
    sales_live = [r for i, r in enumerate(sales_singles) if i not in sales_consumed]
    jofo_live = [r for i, r in enumerate(jofo_singles) if i not in jofo_consumed]

    # Stage 3: split credit notes / reversals from plain invoices.
    def split(
        rows: list[CanonicalInvoice],
    ) -> tuple[list[CanonicalInvoice], list[CanonicalInvoice], list[CanonicalInvoice]]:
        plain = [r for r in rows if not r.is_credit_note and not r.is_reversal]
        credits = [r for r in rows if r.is_credit_note and not r.is_reversal]
        reversals = [r for r in rows if r.is_reversal]
        return plain, credits, reversals

    sales_plain, sales_credits, sales_reversals = split(sales_live)
    jofo_plain, jofo_credits, jofo_reversals = split(jofo_live)

    # Stage 4: single-to-single exact-key matching (never many-to-one: every
    # key is unique on both sides here by construction). Presence needs keys
    # only; comparison additionally needs amounts and currencies — when those
    # are missing on either side the pair is ambiguous, never absent.
    jofo_by_key = {row.key(): row for row in jofo_plain}
    matched_jofo_keys: set[tuple[str, str]] = set()
    for row in sorted(sales_plain, key=_sort_key):
        counterpart = jofo_by_key.get(row.key())
        flags = period_flags((row,) + ((counterpart,) if counterpart else ()))
        if counterpart is None:
            emit(
                UNMATCHED_SALES,
                sales_rows=(row,),
                rationale=("MISSING_IN_JOFOTARA",),
                flags=flags,
            )
            continue
        matched_jofo_keys.add(row.key())
        missing = _value_missing(row) + _value_missing(counterpart)
        if missing:
            emit(
                AMBIGUOUS,
                sales_rows=(row,),
                jofo_rows=(counterpart,),
                rationale=("COMPARISON_INSUFFICIENT", *missing),
                flags=flags,
            )
            continue
        assert row.currency is not None and counterpart.currency is not None
        assert row.amount is not None and counterpart.amount is not None
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
        delta = _exact_delta(row.amount, counterpart.amount)
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

    for row in sorted(jofo_plain, key=_sort_key):
        if row.key() not in matched_jofo_keys:
            emit(
                UNMATCHED_JOFOTARA,
                jofo_rows=(row,),
                rationale=("MISSING_IN_SALES",),
                flags=period_flags((row,)),
            )

    # Stage 5: credit notes and reversals link ONLY through an explicit
    # original-document reference naming a unique existing invoice (same
    # issuer scope); otherwise they are preserved as relationship-unverified
    # (never asserted as linked). Candidate targets include duplicate-cluster
    # members so multi-candidate references stay unverified, never guessed.
    plain_pool = [r for r in (*sales_keyed, *jofo_keyed) if not r.is_credit_note and not r.is_reversal]

    def link(
        row: CanonicalInvoice,
        linked_kind: str,
        unverified_kind: str,
        noun: str,
    ) -> None:
        reference = (row.reference_number or "").strip()
        on_sales = row in sales_credits or row in sales_reversals
        holders = (row,) if on_sales else ()
        holders_jofo = () if on_sales else (row,)
        if not reference:
            emit(
                unverified_kind,
                sales_rows=holders,
                jofo_rows=holders_jofo,
                currency=row.currency,
                rationale=(f"{noun}_PRESERVED",),
                flags=period_flags((row,)) + ("NO_REFERENCE",),
            )
            return
        targets = [r for r in plain_pool if r.number.strip() == reference and r.key()[0] == row.key()[0]]
        if len(targets) != 1:
            emit(
                unverified_kind,
                sales_rows=holders,
                jofo_rows=holders_jofo,
                currency=row.currency,
                rationale=(f"{noun}_PRESERVED",),
                flags=period_flags((row,))
                + (("REFERENCE_UNRESOLVED",) if not targets else ("AMBIGUOUS_TARGET",)),
            )
            return
        (target,) = targets
        target_sales = holders + ((target,) if target in sales_plain else ())
        target_jofo = holders_jofo + ((target,) if target in jofo_plain else ())
        emit(
            linked_kind,
            sales_rows=tuple(sorted(target_sales, key=_sort_key)),
            jofo_rows=tuple(sorted(target_jofo, key=_sort_key)),
            currency=row.currency,
            rationale=(f"{noun}_PRESERVED",),
            flags=period_flags((row, target)) + ("REFERENCE_VERIFIED",),
        )

    for row in sorted((*sales_credits, *jofo_credits), key=_sort_key):
        link(row, CREDIT_NOTE_LINKED, CREDIT_NOTE_UNVERIFIED, "CREDIT_NOTE")
    for row in sorted((*sales_reversals, *jofo_reversals), key=_sort_key):
        link(row, REVERSAL_NOTED, REVERSAL_UNVERIFIED, "REVERSAL")

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
            row.reference_number,
            (
                [
                    row.provenance.dataset_id,
                    row.provenance.source,
                    row.provenance.row_number,
                    row.provenance.raw_invoice,
                ]
                if row.provenance
                else None
            ),
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
