"""Deterministic Sales Register <-> General Ledger comparison (REC-005 slice).

Pure function ``compare_sales_to_gl``. Default-deny: with no approved
``GLComparisonPolicy`` (or any required dimension missing / unsupported) the run
is refused with typed block reasons and no outcome is fabricated. When a policy
verifies, the engine aggregates each side per currency under the declared
convention and compares exact Decimals at the declared tolerance — it never
invents an account scope, sales measure, sign convention, or FX rule.

Rules that hold on every supported path:
- Debit and credit stay independent until the *policy's* convention combines
  them; missing values are never zero and invalid pairs are reported, not netted.
- Currencies never combine; a currency outside the approved scope is refused.
- Duplicates (journal+line on the GL side, issuer+number on the sales side) are
  reported and excluded from the aggregate; a currency bucket touched by a
  duplicate gets no RECONCILED/DIFFERENCE verdict (never a false conclusion).
- Credit notes, reversals, and period-misplaced rows are preserved as linked /
  review records, never netted into totals.
- Arithmetic is integer-scaled and independent of the ambient decimal context;
  fingerprints are stable under any input permutation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, DecimalTuple

from app.recon.gl.contracts import (
    CREDIT_NOTE_LINKED,
    CREDIT_NOTE_UNVERIFIED,
    CURRENCY_NOT_IN_SCOPE,
    DEBIT_POSITIVE,
    DIFFERENCE,
    DUPLICATE_GL,
    DUPLICATE_SALES,
    INVALID_DEBIT_CREDIT_PAIR,
    MISSING_GL,
    MISSING_SALES,
    MISSING_VALUE,
    NO_APPROVED_POLICY,
    PERIOD_OUTSIDE,
    PERIOD_UNKNOWN,
    RECONCILED,
    REVERSAL_NOTED,
    REVERSAL_UNVERIFIED,
    GLComparisonPolicy,
    GLComparisonReport,
    GLComparisonRequest,
    GLLine,
    GLOutcome,
    SalesRegisterEntry,
    rule_for,
)
from app.recon.gl.policy import validate_policy

_ZERO = Decimal("0")


def _exact_add(a: Decimal, b: Decimal) -> Decimal:
    """Exact Decimal addition independent of the ambient context precision."""
    ta, tb = a.as_tuple(), b.as_tuple()
    ea, eb = ta.exponent, tb.exponent
    if isinstance(ea, str) or isinstance(eb, str):
        raise ValueError("non-finite Decimal cannot be aggregated")
    common = ea if ea < eb else eb
    coeff = _signed_coeff(ta) * (10 ** (ea - common)) + _signed_coeff(tb) * (10 ** (eb - common))
    return _decimal_from_coeff(coeff, common)


def _exact_sub(a: Decimal, b: Decimal) -> Decimal:
    return _exact_add(a, b.copy_negate())


def _signed_coeff(t: DecimalTuple) -> int:
    digits = "".join(str(d) for d in t.digits)
    value = int(digits or "0")
    return -value if t.sign else value


def _decimal_from_coeff(coeff: int, exponent: int) -> Decimal:
    if coeff == 0:
        return Decimal((0, (0,), exponent))
    sign = 0 if coeff > 0 else 1
    return Decimal((sign, tuple(int(d) for d in str(abs(coeff))), exponent))


def _gl_sort_key(line: GLLine) -> tuple:
    provenance = line.provenance
    return (
        line.journal_id,
        line.line_number,
        line.account_code,
        line.transaction_date.isoformat() if line.transaction_date else "",
        str(line.debit) if line.debit is not None else "",
        str(line.credit) if line.credit is not None else "",
        line.debit_raw,
        line.credit_raw,
        line.currency or "",
        line.description,
        line.is_reversal,
        line.reversal_reference or "",
        provenance.dataset_id if provenance else "",
        provenance.source if provenance else "",
        provenance.row_number if provenance else 0,
        provenance.raw_reference if provenance else "",
    )


def _sales_sort_key(entry: SalesRegisterEntry) -> tuple:
    provenance = entry.provenance
    return (
        entry.issuer,
        entry.invoice_number,
        str(entry.net_amount) if entry.net_amount is not None else "",
        str(entry.tax_amount) if entry.tax_amount is not None else "",
        str(entry.gross_amount) if entry.gross_amount is not None else "",
        entry.currency or "",
        entry.transaction_date.isoformat() if entry.transaction_date else "",
        entry.is_credit_note,
        entry.is_reversal,
        entry.reference_number or "",
        provenance.dataset_id if provenance else "",
        provenance.source if provenance else "",
        provenance.row_number if provenance else 0,
        provenance.raw_invoice if provenance else "",
    )


def _signed_line(line: GLLine, convention: str) -> Decimal:
    debit = line.debit if line.debit is not None else _ZERO
    credit = line.credit if line.credit is not None else _ZERO
    return (
        _exact_add(debit, credit.copy_negate())
        if convention == DEBIT_POSITIVE
        else _exact_add(credit, debit.copy_negate())
    )


def _window(date_value: date | None, start: date | None, end: date | None) -> str:
    """PERIOD_WITHIN | PERIOD_OUTSIDE | PERIOD_UNKNOWN relative to the request."""
    if start is None and end is None:
        return "PERIOD_WITHIN"
    if date_value is None:
        return "PERIOD_UNKNOWN"
    if (start is not None and date_value < start) or (end is not None and date_value > end):
        return "PERIOD_OUTSIDE"
    return "PERIOD_WITHIN"


def _store(store: dict[str, Decimal], bucket: str, value: Decimal) -> None:
    store[bucket] = _exact_add(store.get(bucket, _ZERO), value)


def compare_sales_to_gl(
    sales: tuple[SalesRegisterEntry, ...],
    gl_lines: tuple[GLLine, ...],
    request: GLComparisonRequest,
) -> GLComparisonReport:
    """Deterministically reconcile sales-register totals against GL (pure)."""
    if not isinstance(sales, tuple) or not isinstance(gl_lines, tuple):
        raise TypeError("sales and gl_lines must be tuples")
    for row in sales:
        if not isinstance(row, SalesRegisterEntry):
            raise TypeError(f"sales must be SalesRegisterEntry, got {type(row).__name__}")
    for line in gl_lines:
        if not isinstance(line, GLLine):
            raise TypeError(f"gl_lines must be GLLine, got {type(line).__name__}")
    if not isinstance(request, GLComparisonRequest):
        raise TypeError("request must be GLComparisonRequest")

    policy = request.policy
    if policy is None:
        return _blocked(request, policy, (NO_APPROVED_POLICY,))
    decision = validate_policy(policy)
    if not decision.approved:
        return _blocked(request, policy, decision.reasons)

    account_scope = policy.account_scope()
    currency_set = policy.currency_set()
    current_measure = policy.sales_measure
    outcomes: list[GLOutcome] = []

    def emit(
        kind: str,
        gl: tuple[GLLine, ...] = (),
        sales_rows: tuple[SalesRegisterEntry, ...] = (),
        sales_total: Decimal | None = None,
        gl_total: Decimal | None = None,
        delta: Decimal | None = None,
        currency: str | None = None,
        rationale: tuple[str, ...] = (),
        flags: tuple[str, ...] = (),
    ) -> None:
        outcomes.append(
            GLOutcome(
                kind=kind,
                rule=rule_for(kind, request.jurisdiction, request.rules_version),
                gl=tuple(sorted(gl, key=_gl_sort_key)),
                sales=tuple(sorted(sales_rows, key=_sales_sort_key)),
                sales_total=sales_total,
                gl_total=gl_total,
                delta=delta,
                currency=currency,
                rationale=rationale,
                flags=flags,
            )
        )

    # -- GL side -------------------------------------------------------------------
    gl_id_counts: dict[tuple[str, int], int] = {}
    for line in gl_lines:
        if line.account_code.strip() in account_scope:
            gl_id_counts[line.identity()] = gl_id_counts.get(line.identity(), 0) + 1
    gl_dup_ids = {key for key, count in gl_id_counts.items() if count > 1}

    in_scope_live: list[GLLine] = []
    gl_out_of_scope = 0
    journal_ids = {line.journal_id.strip() for line in gl_lines}
    for line in sorted(gl_lines, key=_gl_sort_key):
        if line.account_code.strip() not in account_scope:
            gl_out_of_scope += 1
            continue
        if line.is_reversal:
            reference = (line.reversal_reference or "").strip()
            if reference and reference in journal_ids:
                emit(
                    REVERSAL_NOTED,
                    gl=(line,),
                    rationale=("REVERSAL_PRESERVED",),
                    flags=("REFERENCE_VERIFIED",),
                )
            else:
                flags = () if reference else ("NO_REFERENCE",)
                if reference:
                    flags = ("REFERENCE_UNRESOLVED",)
                emit(REVERSAL_UNVERIFIED, gl=(line,), rationale=("REVERSAL_PRESERVED",), flags=flags)
            continue
        if line.debit is not None and line.credit is not None:
            emit(INVALID_DEBIT_CREDIT_PAIR, gl=(line,), rationale=("DEBIT_AND_CREDIT_PRESENT",))
            continue
        if line.debit is None and line.credit is None:
            emit(MISSING_VALUE, gl=(line,), rationale=("MISSING_AMOUNT",))
            continue
        if line.currency is None:
            emit(MISSING_VALUE, gl=(line,), rationale=("MISSING_CURRENCY",))
            continue
        if line.currency not in currency_set:
            emit(
                CURRENCY_NOT_IN_SCOPE,
                gl=(line,),
                currency=line.currency,
                rationale=("CURRENCY_NOT_APPROVED",),
            )
            continue
        placement = _window(line.transaction_date, request.period_start, request.period_end)
        if placement == PERIOD_UNKNOWN:
            emit(PERIOD_UNKNOWN, gl=(line,), currency=line.currency, rationale=("PERIOD_UNKNOWN",))
            continue
        if placement == PERIOD_OUTSIDE:
            emit(PERIOD_OUTSIDE, gl=(line,), currency=line.currency, rationale=("PERIOD_OUTSIDE",))
            continue
        if line.identity() in gl_dup_ids:
            continue  # reported as a duplicate cluster below
        in_scope_live.append(line)

    for key in sorted(gl_dup_ids):
        members = tuple(line for line in gl_lines if line.identity() == key)
        emit(DUPLICATE_GL, gl=members, rationale=("DUPLICATE_JOURNAL_LINE",))

    # -- sales side ----------------------------------------------------------------
    sales_key_counts: dict[tuple[str, str], int] = {}
    for entry in sales:
        if not entry.is_credit_note and not entry.is_reversal:
            sales_key_counts[entry.key()] = sales_key_counts.get(entry.key(), 0) + 1
    sales_dup_keys = {key for key, count in sales_key_counts.items() if count > 1}
    sales_numbers = {(e.issuer.strip().casefold(), e.invoice_number.strip()) for e in sales}

    sales_live: list[tuple[SalesRegisterEntry, Decimal]] = []
    for entry in sorted(sales, key=_sales_sort_key):
        if entry.is_reversal:
            reference = (entry.reference_number or "").strip()
            if reference and (entry.issuer.strip().casefold(), reference) in sales_numbers:
                emit(
                    REVERSAL_NOTED,
                    sales_rows=(entry,),
                    rationale=("REVERSAL_PRESERVED",),
                    flags=("REFERENCE_VERIFIED",),
                )
            else:
                flags = ("REFERENCE_UNRESOLVED",) if reference else ("NO_REFERENCE",)
                emit(REVERSAL_UNVERIFIED, sales_rows=(entry,), rationale=("REVERSAL_PRESERVED",), flags=flags)
            continue
        if entry.is_credit_note:
            reference = (entry.reference_number or "").strip()
            if reference and (entry.issuer.strip().casefold(), reference) in sales_numbers:
                emit(
                    CREDIT_NOTE_LINKED,
                    sales_rows=(entry,),
                    rationale=("CREDIT_NOTE_PRESERVED",),
                    flags=("REFERENCE_VERIFIED",),
                )
            else:
                flags = ("REFERENCE_UNRESOLVED",) if reference else ("NO_REFERENCE",)
                emit(
                    CREDIT_NOTE_UNVERIFIED,
                    sales_rows=(entry,),
                    rationale=("CREDIT_NOTE_PRESERVED",),
                    flags=flags,
                )
            continue
        amount, _raw = entry.measure(current_measure)
        if amount is None:
            emit(MISSING_VALUE, sales_rows=(entry,), rationale=(f"MISSING_{current_measure}",))
            continue
        if entry.currency is None:
            emit(MISSING_VALUE, sales_rows=(entry,), rationale=("MISSING_CURRENCY",))
            continue
        if entry.currency not in currency_set:
            emit(
                CURRENCY_NOT_IN_SCOPE,
                sales_rows=(entry,),
                currency=entry.currency,
                rationale=("CURRENCY_NOT_APPROVED",),
            )
            continue
        placement = _window(entry.transaction_date, request.period_start, request.period_end)
        if placement == PERIOD_UNKNOWN:
            emit(PERIOD_UNKNOWN, sales_rows=(entry,), currency=entry.currency, rationale=("PERIOD_UNKNOWN",))
            continue
        if placement == PERIOD_OUTSIDE:
            emit(PERIOD_OUTSIDE, sales_rows=(entry,), currency=entry.currency, rationale=("PERIOD_OUTSIDE",))
            continue
        if entry.key() in sales_dup_keys:
            continue  # reported as a duplicate cluster below
        sales_live.append((entry, amount))

    for sales_key in sorted(sales_dup_keys):
        sales_members = tuple(
            e for e in sales if e.key() == sales_key and not e.is_credit_note and not e.is_reversal
        )
        emit(DUPLICATE_SALES, sales_rows=sales_members, rationale=("DUPLICATE_INVOICE_KEY",))

    # -- aggregate per currency and compare ----------------------------------------
    gl_totals: dict[str, Decimal] = {}
    gl_rows: dict[str, list[GLLine]] = {}
    for line in in_scope_live:
        assert line.currency is not None
        _store(gl_totals, line.currency, _signed_line(line, policy.debit_credit_convention))
        gl_rows.setdefault(line.currency, []).append(line)

    sales_totals: dict[str, Decimal] = {}
    sales_rows_by_currency: dict[str, list[SalesRegisterEntry]] = {}
    for entry, amount in sales_live:
        assert entry.currency is not None
        _store(sales_totals, entry.currency, amount)
        sales_rows_by_currency.setdefault(entry.currency, []).append(entry)

    dup_currencies = {
        line.currency for line in gl_lines if line.identity() in gl_dup_ids and line.currency
    } | {e.currency for e in sales if e.key() in sales_dup_keys and e.currency}

    for currency in sorted(set(gl_totals) | set(sales_totals)):
        if currency in dup_currencies:
            continue  # duplicate-contaminated bucket: no verdict (already reported)
        gl_value = gl_totals.get(currency)
        sales_value = sales_totals.get(currency)
        g_rows = tuple(gl_rows.get(currency, ()))
        s_rows = tuple(sales_rows_by_currency.get(currency, ()))
        if sales_value is None:
            emit(MISSING_SALES, gl=g_rows, currency=currency, rationale=("NO_SALES_IN_PERIOD",))
            continue
        if gl_value is None:
            emit(MISSING_GL, sales_rows=s_rows, currency=currency, rationale=("NO_GL_IN_PERIOD",))
            continue
        delta = _exact_sub(sales_value, gl_value)
        flags = ("WITHIN_TOLERANCE",) if delta != _ZERO else ()
        if abs(delta) <= policy.tolerance:
            emit(
                RECONCILED,
                gl=g_rows,
                sales_rows=s_rows,
                sales_total=sales_value,
                gl_total=gl_value,
                delta=delta,
                currency=currency,
                rationale=("TOTALS_AGREE",),
                flags=flags,
            )
        else:
            emit(
                DIFFERENCE,
                gl=g_rows,
                sales_rows=s_rows,
                sales_total=sales_value,
                gl_total=gl_value,
                delta=delta,
                currency=currency,
                rationale=("TOTALS_DIFFER",),
            )

    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.kind] = counts.get(outcome.kind, 0) + 1
    return GLComparisonReport(
        tenant_id=request.tenant_id,
        client_id=request.client_id,
        sales_dataset_id=request.sales_dataset_id,
        gl_dataset_id=request.gl_dataset_id,
        jurisdiction=request.jurisdiction,
        rules_version=request.rules_version,
        comparison_basis=policy.comparison_basis,
        sales_measure=policy.sales_measure,
        gl_account_scope=tuple(sorted(account_scope)),
        debit_credit_convention=policy.debit_credit_convention,
        currency_scope=tuple(sorted(currency_set)),
        tolerance=policy.tolerance,
        period_start=request.period_start,
        period_end=request.period_end,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        blocked=False,
        block_reasons=(),
        outcomes=tuple(outcomes),
        counts=counts,
        sales_total=len(sales),
        gl_total=len(gl_lines),
        gl_out_of_scope=gl_out_of_scope,
        fingerprint=_fingerprint(
            request,
            policy.policy_id,
            policy.policy_version,
            policy.comparison_basis,
            policy.sales_measure,
            policy.debit_credit_convention,
            tuple(sorted(account_scope)),
            tuple(sorted(currency_set)),
            policy.tolerance,
            False,
            (),
            outcomes,
        ),
    )


def _blocked(
    request: GLComparisonRequest, policy: GLComparisonPolicy | None, reasons: tuple[str, ...]
) -> GLComparisonReport:
    pid = policy.policy_id if policy is not None else None
    pver = policy.policy_version if policy is not None else None
    basis = policy.comparison_basis if policy is not None else None
    measure = policy.sales_measure if policy is not None else None
    convention = policy.debit_credit_convention if policy is not None else None
    scope = tuple(sorted(policy.account_scope())) if policy is not None else ()
    currencies = tuple(sorted(policy.currency_set())) if policy is not None else ()
    tolerance = policy.tolerance if policy is not None else None
    return GLComparisonReport(
        tenant_id=request.tenant_id,
        client_id=request.client_id,
        sales_dataset_id=request.sales_dataset_id,
        gl_dataset_id=request.gl_dataset_id,
        jurisdiction=request.jurisdiction,
        rules_version=request.rules_version,
        comparison_basis=basis,
        sales_measure=measure,
        gl_account_scope=scope,
        debit_credit_convention=convention,
        currency_scope=currencies,
        tolerance=tolerance,
        period_start=request.period_start,
        period_end=request.period_end,
        policy_id=pid,
        policy_version=pver,
        blocked=True,
        block_reasons=reasons,
        outcomes=(),
        counts={},
        sales_total=0,
        gl_total=0,
        gl_out_of_scope=0,
        fingerprint=_fingerprint(
            request, pid, pver, basis, measure, convention, scope, currencies, tolerance, True, reasons, []
        ),
    )


def _fingerprint(
    request: GLComparisonRequest,
    policy_id: object,
    policy_version: object,
    basis: object,
    measure: object,
    convention: object,
    scope: tuple[str, ...],
    currencies: tuple[str, ...],
    tolerance: object,
    blocked: bool,
    block_reasons: tuple[str, ...],
    outcomes: list[GLOutcome],
) -> str:
    def gl_blob(line: GLLine) -> object:
        return [
            line.journal_id,
            line.line_number,
            line.account_code,
            line.transaction_date.isoformat() if line.transaction_date else None,
            str(line.debit) if line.debit is not None else None,
            str(line.credit) if line.credit is not None else None,
            line.debit_raw,
            line.credit_raw,
            line.currency,
            line.description,
            line.is_reversal,
            line.reversal_reference,
            (
                [
                    line.provenance.dataset_id,
                    line.provenance.source,
                    line.provenance.row_number,
                    line.provenance.raw_reference,
                ]
                if line.provenance
                else None
            ),
        ]

    def sales_blob(entry: SalesRegisterEntry) -> object:
        return [
            entry.issuer,
            entry.invoice_number,
            str(entry.net_amount) if entry.net_amount is not None else None,
            str(entry.tax_amount) if entry.tax_amount is not None else None,
            str(entry.gross_amount) if entry.gross_amount is not None else None,
            entry.currency,
            entry.transaction_date.isoformat() if entry.transaction_date else None,
            entry.is_credit_note,
            entry.is_reversal,
            entry.reference_number,
            (
                [
                    entry.provenance.dataset_id,
                    entry.provenance.source,
                    entry.provenance.row_number,
                    entry.provenance.raw_invoice,
                ]
                if entry.provenance
                else None
            ),
        ]

    def outcome_blob(outcome: GLOutcome) -> object:
        return [
            outcome.kind,
            outcome.rule,
            [gl_blob(line) for line in outcome.gl],
            [sales_blob(entry) for entry in outcome.sales],
            str(outcome.sales_total) if outcome.sales_total is not None else None,
            str(outcome.gl_total) if outcome.gl_total is not None else None,
            str(outcome.delta) if outcome.delta is not None else None,
            outcome.currency,
            list(outcome.rationale),
            list(outcome.flags),
        ]

    payload = {
        "tenant": request.tenant_id,
        "client": request.client_id,
        "sales_dataset": request.sales_dataset_id,
        "gl_dataset": request.gl_dataset_id,
        "jurisdiction": request.jurisdiction,
        "rules": request.rules_version,
        "policy": [policy_id, policy_version, basis, measure, convention],
        "scope": list(scope),
        "currencies": list(currencies),
        "tolerance": str(tolerance) if tolerance is not None else None,
        "period": [
            request.period_start.isoformat() if request.period_start else None,
            request.period_end.isoformat() if request.period_end else None,
        ],
        "blocked": blocked,
        "block_reasons": list(block_reasons),
        "outcomes": sorted(
            [outcome_blob(o) for o in outcomes], key=lambda blob: json.dumps(blob, sort_keys=True)
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "compare_sales_to_gl",
]
