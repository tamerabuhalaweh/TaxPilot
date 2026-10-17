"""REC-005 Sales Register <-> General Ledger reconciliation contracts.

Pure, immutable, I/O-free domain contracts for the third comparison domain
(SRS Master v2.0 REC-005: "Sales Register -> GL; mapped totals vs GL with
mappings/periods/currencies/adjustments/tolerances"). This module defines the
input shapes and the explicit comparison *policy*; it never invents an
accounting rule.

Grounding and honest limits
---------------------------
The approved normalized GL contract exposes only
``account_code, transaction_date, debit_amount, credit_amount, currency,
description`` (``app.normalization.contracts.GL_FIELDS``). There is **no**
invoice-reference column, no account taxonomy, and no approved sales->account
mapping anywhere in the repository or SRS. Therefore:

- The only *grounded* comparison level is **aggregate by period** over an
  explicitly approved account scope (``BASIS_AGGREGATE_PERIOD``). Which accounts
  represent the sales-side postings, which sales measure to compare, and how a
  debit/credit posting is signed are **accounting decisions** the caller must
  supply as an approved :class:`GLComparisonPolicy`; the engine applies them and
  makes no assumption of its own.
- Invoice-to-GL-line matching is declared (``BASIS_INVOICE_REFERENCE``) but
  **unsupported**: it needs a verified GL reference field / mapping that does
  not exist yet. Requesting it is refused, never approximated.

Default-deny: with no approved policy (or any required dimension missing) a run
is BLOCKED with typed reasons and no output is fabricated. A caller-constructed
"approved" policy is a *declared claim*, not production authorization; real
approval requires a trusted, independently verified policy source (see
``docs/product/REC-GL-01-boundary.md``).

No database, HTTP, network, float, LLM, or tax interpretation anywhere here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.recon.contracts import InvoiceProvenance

GL_SOURCE = "general_ledger"

# Comparison basis -----------------------------------------------------------------
BASIS_AGGREGATE_PERIOD = "AGGREGATE_PERIOD"
BASIS_INVOICE_REFERENCE = "INVOICE_REFERENCE"
SUPPORTED_BASES = (BASIS_AGGREGATE_PERIOD,)

# Sales measure selected for the comparison ----------------------------------------
MEASURE_NET = "NET"
MEASURE_TAX = "TAX"
MEASURE_GROSS = "GROSS"
SALES_MEASURES = (MEASURE_NET, MEASURE_TAX, MEASURE_GROSS)

# Explicit debit/credit sign convention --------------------------------------------
DEBIT_POSITIVE = "DEBIT_POSITIVE"
CREDIT_POSITIVE = "CREDIT_POSITIVE"
CONVENTIONS = (DEBIT_POSITIVE, CREDIT_POSITIVE)

POLICY_APPROVED = "APPROVED"
POLICY_DRAFT = "DRAFT"

# Block reasons (typed, stable machine codes) --------------------------------------
NO_APPROVED_POLICY = "NO_APPROVED_POLICY"
POLICY_NOT_APPROVED = "POLICY_NOT_APPROVED"
POLICY_MISSING_PROVENANCE = "POLICY_MISSING_PROVENANCE"
POLICY_MISSING_BASIS = "POLICY_MISSING_BASIS"
POLICY_UNSUPPORTED_BASIS = "POLICY_UNSUPPORTED_BASIS"
POLICY_MISSING_ACCOUNT_SCOPE = "POLICY_MISSING_ACCOUNT_SCOPE"
POLICY_MISSING_CURRENCY_SCOPE = "POLICY_MISSING_CURRENCY_SCOPE"
POLICY_MISSING_SALES_MEASURE = "POLICY_MISSING_SALES_MEASURE"
POLICY_MISSING_CONVENTION = "POLICY_MISSING_CONVENTION"

# Outcome kinds --------------------------------------------------------------------
RECONCILED = "RECONCILED"
DIFFERENCE = "DIFFERENCE"
MISSING_GL = "MISSING_GL"
MISSING_SALES = "MISSING_SALES"
DUPLICATE_GL = "DUPLICATE_GL"
DUPLICATE_SALES = "DUPLICATE_SALES"
INVALID_DEBIT_CREDIT_PAIR = "INVALID_DEBIT_CREDIT_PAIR"
MISSING_VALUE = "MISSING_VALUE"
CURRENCY_NOT_IN_SCOPE = "CURRENCY_NOT_IN_SCOPE"
PERIOD_OUTSIDE = "PERIOD_OUTSIDE"
PERIOD_UNKNOWN = "PERIOD_UNKNOWN"
REVERSAL_NOTED = "REVERSAL_NOTED"
REVERSAL_UNVERIFIED = "REVERSAL_UNVERIFIED"
CREDIT_NOTE_LINKED = "CREDIT_NOTE_LINKED"
CREDIT_NOTE_UNVERIFIED = "CREDIT_NOTE_UNVERIFIED"
# F1: emitted instead of RECONCILED/DIFFERENCE/MISSING_* for a currency whose
# coverage is incomplete (invalid/ambiguous/unassignable records were excluded),
# so an affirmative result is never produced from partial data.
INCONCLUSIVE_COVERAGE = "INCONCLUSIVE_COVERAGE"

# Coverage-contamination reason codes (carried on inconclusive outcomes and on
# the report's ``inconclusive_reasons`` for unassignable/global contamination).
COVERAGE_MISSING_CURRENCY = "COVERAGE_MISSING_CURRENCY"
COVERAGE_CURRENCY_OUT_OF_SCOPE = "COVERAGE_CURRENCY_OUT_OF_SCOPE"
COVERAGE_INVALID_DEBIT_CREDIT_PAIR = "COVERAGE_INVALID_DEBIT_CREDIT_PAIR"
COVERAGE_MISSING_AMOUNT = "COVERAGE_MISSING_AMOUNT"
COVERAGE_MISSING_MEASURE = "COVERAGE_MISSING_MEASURE"
COVERAGE_PERIOD_UNKNOWN = "COVERAGE_PERIOD_UNKNOWN"
COVERAGE_DUPLICATE = "COVERAGE_DUPLICATE"
COVERAGE_UNVERIFIED_RELATIONSHIP = "COVERAGE_UNVERIFIED_RELATIONSHIP"

_RULE_BY_KIND = {
    RECONCILED: "REC-005",
    DIFFERENCE: "REC-005",
    MISSING_GL: "REC-005",
    MISSING_SALES: "REC-005",
    DUPLICATE_GL: "REC-005",
    DUPLICATE_SALES: "REC-005",
    INVALID_DEBIT_CREDIT_PAIR: "NOTE",
    MISSING_VALUE: "NOTE",
    CURRENCY_NOT_IN_SCOPE: "NOTE",
    PERIOD_OUTSIDE: "NOTE",
    PERIOD_UNKNOWN: "NOTE",
    REVERSAL_NOTED: "NOTE",
    REVERSAL_UNVERIFIED: "NOTE",
    CREDIT_NOTE_LINKED: "NOTE",
    CREDIT_NOTE_UNVERIFIED: "NOTE",
    INCONCLUSIVE_COVERAGE: "NOTE",
}

KNOWN_OUTCOME_KINDS = tuple(_RULE_BY_KIND)

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _normalize_currency(value: str | None, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    normalized = value.strip().upper()
    if not _CURRENCY_RE.match(normalized):
        raise ValueError(f"{label} must be an explicit 3-letter code, got {value!r}")
    return normalized


def _positive_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be a genuine int (no bool, float, or str)")
    if value < 1:
        raise ValueError(f"{label} must be >= 1")
    return value


def _optional_decimal(value: Decimal | None, *, label: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise TypeError(f"{label} must be Decimal, got {type(value).__name__}; no float/int path")
    if value.is_nan() or value.is_infinite():
        raise ValueError(f"{label} must be finite")
    return value


@dataclass(frozen=True)
class GLEntryProvenance:
    """Source anchor for one GL line (dataset + source + row + raw text)."""

    dataset_id: str
    source: str  # general_ledger
    row_number: int
    raw_reference: str

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_id, str) or not self.dataset_id.strip():
            raise ValueError("dataset_id must be a non-blank string")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be a non-blank string")
        if not isinstance(self.raw_reference, str):
            raise TypeError("raw_reference must be text (original source value)")
        _positive_int(self.row_number, label="row_number")


@dataclass(frozen=True)
class GLLine:
    """One journal line: debit and credit kept independent, never netted here.

    ``debit``/``credit`` are exact Decimals or None (missing is never zero); a
    line may legitimately omit both (reported as missing, never zero-filled) and
    a line carrying both is preserved for the engine to classify as an invalid
    pair (AQ-008), never silently netted at construction. Reversals are linked
    records, not netted. Account codes stay verbatim strings (leading zeros
    preserved).
    """

    journal_id: str
    line_number: int
    account_code: str
    transaction_date: date | None
    debit: Decimal | None
    credit: Decimal | None
    debit_raw: str
    credit_raw: str
    currency: str | None
    description: str = ""
    is_reversal: bool = False
    reversal_reference: str | None = None
    provenance: GLEntryProvenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.journal_id, str) or not self.journal_id.strip():
            raise ValueError("journal_id must be a non-blank string")
        _positive_int(self.line_number, label="line_number")
        if not isinstance(self.account_code, str) or not self.account_code.strip():
            raise ValueError("account_code must be a non-blank string")
        if self.transaction_date is not None and not isinstance(self.transaction_date, date):
            raise TypeError("transaction_date must be a date or None")
        _optional_decimal(self.debit, label="debit")
        _optional_decimal(self.credit, label="credit")
        if not isinstance(self.debit_raw, str) or not isinstance(self.credit_raw, str):
            raise TypeError("debit_raw/credit_raw must be text (original source values)")
        object.__setattr__(self, "currency", _normalize_currency(self.currency, label="currency"))
        if not isinstance(self.description, str):
            raise TypeError("description must be text")
        if not isinstance(self.is_reversal, bool):
            raise TypeError("is_reversal must be bool")
        if self.reversal_reference is not None:
            if not isinstance(self.reversal_reference, str):
                raise TypeError("reversal_reference must be text")
            if not self.reversal_reference.strip():
                object.__setattr__(self, "reversal_reference", None)
        if self.provenance is not None and not isinstance(self.provenance, GLEntryProvenance):
            raise TypeError("provenance must be GLEntryProvenance")

    def identity(self) -> tuple[str, int]:
        """Journal + line identity (stripped; the natural GL line key)."""
        return (self.journal_id.strip(), self.line_number)


@dataclass(frozen=True)
class SalesRegisterEntry:
    """One normalized sales-register row with all three measures available.

    The comparison *policy* selects which measure is compared, so no measure is
    privileged here. Identifiers stay verbatim strings; amounts are exact
    Decimals or None (never zero); credit notes and reversals are linked
    records, never netted.
    """

    issuer: str
    invoice_number: str
    net_amount: Decimal | None
    net_raw: str
    tax_amount: Decimal | None
    tax_raw: str
    gross_amount: Decimal | None
    gross_raw: str
    currency: str | None
    transaction_date: date | None
    is_credit_note: bool = False
    is_reversal: bool = False
    reference_number: str | None = None
    provenance: InvoiceProvenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.issuer, str) or not isinstance(self.invoice_number, str):
            raise TypeError("issuer and invoice_number must be text (identifiers stay strings)")
        for label, value, raw in (
            ("net_amount", self.net_amount, self.net_raw),
            ("tax_amount", self.tax_amount, self.tax_raw),
            ("gross_amount", self.gross_amount, self.gross_raw),
        ):
            _optional_decimal(value, label=label)
            if not isinstance(raw, str):
                raise TypeError(f"{label.replace('_amount', '_raw')} must be text")
        if self.transaction_date is not None and not isinstance(self.transaction_date, date):
            raise TypeError("transaction_date must be a date or None")
        object.__setattr__(self, "currency", _normalize_currency(self.currency, label="currency"))
        if not isinstance(self.is_credit_note, bool) or not isinstance(self.is_reversal, bool):
            raise TypeError("is_credit_note/is_reversal must be bool")
        if self.reference_number is not None:
            if not isinstance(self.reference_number, str):
                raise TypeError("reference_number must be text")
            if not self.reference_number.strip():
                object.__setattr__(self, "reference_number", None)
        if self.provenance is not None and not isinstance(self.provenance, InvoiceProvenance):
            raise TypeError("provenance must be InvoiceProvenance")

    def key(self) -> tuple[str, str]:
        """Issuer + number identity (never number alone; case-folded issuer)."""
        return (self.issuer.strip().casefold(), self.invoice_number.strip())

    def measure(self, measure: str) -> tuple[Decimal | None, str]:
        """Return (amount, raw) for the selected measure (unknown measure -> None)."""
        if measure == MEASURE_NET:
            return self.net_amount, self.net_raw
        if measure == MEASURE_TAX:
            return self.tax_amount, self.tax_raw
        if measure == MEASURE_GROSS:
            return self.gross_amount, self.gross_raw
        raise ValueError(f"unknown sales measure: {measure!r}")


@dataclass(frozen=True)
class GLPolicyProvenance:
    """Declared origin/authority of an approved comparison policy (never inferred).

    These are *declared claims*, not proof: a caller can set them on any object.
    Genuine authorization requires a trusted, independently verified policy
    source; this dataclass does not itself authorize production runs.
    """

    authority: str
    reference: str
    effective_from: date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.authority, str) or not self.authority.strip():
            raise ValueError("authority must be a non-blank string")
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError("reference must be a non-blank string")
        if self.effective_from is not None and not isinstance(self.effective_from, date):
            raise TypeError("effective_from must be a date or None")


@dataclass(frozen=True)
class GLComparisonPolicy:
    """Explicit, approved accounting policy governing one REC-005 comparison.

    Every dimension is caller-supplied and validated; nothing is defaulted.
    ``gl_account_scope`` and ``currency_scope`` are explicit allow-lists (no
    wildcard, no FX). ``debit_credit_convention`` fixes how a line's debit/credit
    columns are signed before aggregation. ``sales_measure`` selects which sales
    amount is compared. Structural type errors raise; incompleteness is reported
    by :func:`policy.validate_policy` as typed block reasons (default-deny).

    Trust boundary (F2): constructing this object — even with
    ``status="APPROVED"``, an ``approved_by`` name, and provenance — is only a
    *declared claim*. It is NOT proof of an authorized accounting policy, and a
    positive report built from it is a synthetic, conditional pure-domain
    calculation, not production authority. A live integration must instead bind,
    against a trusted independently verified registry: tenant, client,
    engagement, policy id/version, the reviewer authorization (server-verified,
    never a self-declared string), and the exact account scope, measure,
    convention, currency scope, period, and tolerance applied. See
    ``policy.py`` and ``docs/product/REC-GL-01-boundary.md``.
    """

    policy_id: str
    policy_version: str
    status: str
    comparison_basis: str
    sales_measure: str
    gl_account_scope: tuple[str, ...]
    debit_credit_convention: str
    currency_scope: tuple[str, ...]
    tolerance: Decimal = Decimal("0")
    rules_version: str = "1"
    approved_by: str = ""
    approved_at: str = ""
    provenance: GLPolicyProvenance | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
            ("status", self.status),
            ("rules_version", self.rules_version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be a non-blank string")
        if self.status not in (POLICY_APPROVED, POLICY_DRAFT):
            raise ValueError(f"status must be {POLICY_APPROVED!r} or {POLICY_DRAFT!r}")
        for label, value in (
            ("comparison_basis", self.comparison_basis),
            ("sales_measure", self.sales_measure),
            ("debit_credit_convention", self.debit_credit_convention),
        ):
            if not isinstance(value, str):
                raise TypeError(f"{label} must be text")
        for label, scope in (
            ("gl_account_scope", self.gl_account_scope),
            ("currency_scope", self.currency_scope),
        ):
            if not isinstance(scope, tuple) or any(not isinstance(item, str) for item in scope):
                raise TypeError(f"{label} must be a tuple of str")
        if not isinstance(self.tolerance, Decimal):
            raise TypeError("tolerance must be Decimal (no float thresholds)")
        if self.tolerance < 0:
            raise ValueError("tolerance must be >= 0")
        if self.tolerance.is_nan() or self.tolerance.is_infinite():
            raise ValueError("non-finite tolerance rejected")
        if not isinstance(self.approved_by, str) or not isinstance(self.approved_at, str):
            raise TypeError("approved_by/approved_at must be text")
        if self.provenance is not None and not isinstance(self.provenance, GLPolicyProvenance):
            raise TypeError("provenance must be GLPolicyProvenance")

    def account_scope(self) -> frozenset[str]:
        """Normalized account scope (stripped, exact — leading zeros preserved)."""
        return frozenset(code.strip() for code in self.gl_account_scope)

    def currency_set(self) -> frozenset[str]:
        return frozenset(code.strip().upper() for code in self.currency_scope)


@dataclass(frozen=True)
class GLPolicyRegistry:
    """Immutable set of declared policies (default is empty / no approved policy).

    A registry only holds declared manifests. Constructing one does not grant
    production trust; genuine authorization requires a trusted, independently
    verified source built through the accounting approval gate.
    """

    policies: tuple[GLComparisonPolicy, ...] = ()

    def find(self, *, comparison_basis: str, sales_measure: str, currency: str) -> GLComparisonPolicy | None:
        """Return the unique declared policy matching the request, else None.

        Ambiguity (more than one match) yields None so the caller fails closed
        rather than picking arbitrarily.
        """
        matches = [
            policy
            for policy in self.policies
            if policy.comparison_basis == comparison_basis
            and policy.sales_measure == sales_measure
            and currency.strip().upper() in policy.currency_set()
        ]
        return matches[0] if len(matches) == 1 else None


DEFAULT_GL_POLICY_REGISTRY = GLPolicyRegistry()


@dataclass(frozen=True)
class GLComparisonRequest:
    """Explicit run scope plus the governing policy (None means no policy)."""

    tenant_id: str
    client_id: str
    sales_dataset_id: str
    gl_dataset_id: str
    jurisdiction: str
    rules_version: str
    policy: GLComparisonPolicy | None
    period_start: date | None = None
    period_end: date | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("tenant_id", self.tenant_id),
            ("client_id", self.client_id),
            ("sales_dataset_id", self.sales_dataset_id),
            ("gl_dataset_id", self.gl_dataset_id),
            ("jurisdiction", self.jurisdiction),
            ("rules_version", self.rules_version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be a non-blank string")
        if self.policy is not None and not isinstance(self.policy, GLComparisonPolicy):
            raise TypeError("policy must be GLComparisonPolicy or None")


@dataclass(frozen=True)
class GLOutcome:
    """One deterministic REC-005 outcome with exact evidence.

    ``sales_total``/``gl_total`` are the exact Decimals aggregated under the
    approved policy (None when not applicable); ``delta`` is sales minus GL
    under the declared convention (never across currencies).
    """

    kind: str
    rule: str
    gl: tuple[GLLine, ...] = field(default_factory=tuple)
    sales: tuple[SalesRegisterEntry, ...] = field(default_factory=tuple)
    sales_total: Decimal | None = None
    gl_total: Decimal | None = None
    delta: Decimal | None = None
    currency: str | None = None
    rationale: tuple[str, ...] = field(default_factory=tuple)
    flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GLComparisonReport:
    """Deterministic, fingerprinted REC-005 run result (stable under reorder).

    ``blocked`` is True when the run was refused (default-deny); then
    ``block_reasons`` is non-empty and ``outcomes`` is empty.

    ``inconclusive`` is True when at least one in-scope record could not be
    placed or validated, so coverage is incomplete (F1). Then no currency can
    carry an affirmative ``RECONCILED``/``DIFFERENCE``/``MISSING_*`` verdict;
    affected currencies are reported as ``INCONCLUSIVE_COVERAGE`` and
    ``inconclusive_reasons`` lists the coverage-contamination codes.
    """

    tenant_id: str
    client_id: str
    sales_dataset_id: str
    gl_dataset_id: str
    jurisdiction: str
    rules_version: str
    comparison_basis: str | None
    sales_measure: str | None
    gl_account_scope: tuple[str, ...]
    debit_credit_convention: str | None
    currency_scope: tuple[str, ...]
    tolerance: Decimal | None
    period_start: date | None
    period_end: date | None
    policy_id: str | None
    policy_version: str | None
    blocked: bool
    block_reasons: tuple[str, ...]
    inconclusive: bool
    inconclusive_reasons: tuple[str, ...]
    outcomes: tuple[GLOutcome, ...]
    counts: dict[str, int]
    sales_total: int
    gl_total: int
    gl_out_of_scope: int
    fingerprint: str


def rule_for(kind: str, jurisdiction: str, rules_version: str) -> str:
    """Evidence rule reference, e.g. ``JO/REC-005/1`` (NOTE for non-rule kinds)."""
    return f"{jurisdiction}/{_RULE_BY_KIND[kind]}/{rules_version}"
