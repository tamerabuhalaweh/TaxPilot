"""REC-001..004 sales↔JoFotara deterministic matching (pure domain, no I/O).

SRS mapping (Master SRS v2.0 §7; specified behavior, integration later):
- REC-001 sales without JoFotara counterpart -> UNMATCHED_SALES.
- REC-002 JoFotara without sales counterpart -> UNMATCHED_JOFOTARA.
- REC-003 matched amount differences (exact Decimal deltas, explicit tolerance
  recorded in evidence; multi-field net/tax/gross comparison deferred until
  approved JoFotara profiles expose those fields).
- REC-004 duplicates (deterministic exact-key clusters; suspicious is never
  fraud, never a legal violation — outcomes state possible-issues only).
Matching MUST distinguish exact/unmatched/ambiguous/diff/insufficient;
preserve issuer + invoice identity (never number alone); honor credit notes
and reversals as linked records without netting; forbid many-to-one
auto-match; exact decimals; never silent zero/FX; surface period diffs via
flags; record strategy + versions + tolerances. Missing fields -->
INSUFFICIENT_DATA (NOT RUN for that row), never zero-filled.

No database, HTTP, network, float, LLM, or tax interpretation anywhere here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

SALES_SOURCE = "sales_register"
JOFO_SOURCE = "jofotara_export"

EXACT_MATCH = "EXACT_MATCH"
AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
UNMATCHED_SALES = "UNMATCHED_SALES"
UNMATCHED_JOFOTARA = "UNMATCHED_JOFOTARA"
DUPLICATE_SALES = "DUPLICATE_SALES"
DUPLICATE_JOFOTARA = "DUPLICATE_JOFOTARA"
AMBIGUOUS = "AMBIGUOUS"
CREDIT_NOTE_LINKED = "CREDIT_NOTE_LINKED"
CREDIT_NOTE_UNVERIFIED = "CREDIT_NOTE_UNVERIFIED"
REVERSAL_NOTED = "REVERSAL_NOTED"
REVERSAL_UNVERIFIED = "REVERSAL_UNVERIFIED"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

_RULE_BY_KIND = {
    EXACT_MATCH: "REC-003",
    AMOUNT_MISMATCH: "REC-003",
    UNMATCHED_SALES: "REC-001",
    UNMATCHED_JOFOTARA: "REC-002",
    DUPLICATE_SALES: "REC-004",
    DUPLICATE_JOFOTARA: "REC-004",
    AMBIGUOUS: "REC-003",
    CREDIT_NOTE_LINKED: "NOTE",
    CREDIT_NOTE_UNVERIFIED: "NOTE",
    REVERSAL_NOTED: "NOTE",
    REVERSAL_UNVERIFIED: "NOTE",
    INSUFFICIENT_DATA: "NOTE",
}

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class InvoiceProvenance:
    """Source anchor for one invoice row (dataset + row + raw texts)."""

    dataset_id: str
    source: str  # sales_register | jofotara_export
    row_number: int
    raw_invoice: str


@dataclass(frozen=True)
class CanonicalInvoice:
    """One matchable invoice with exact Decimal amount and full provenance.

    Identifiers stay verbatim strings (leading zeros preserved). ``amount`` is
    the configured compare amount (net for sales); None means missing (never
    zero). Credit notes and reversals are linked records, never netted: a link
    is only asserted when ``reference_number`` names an existing invoice
    (verified); otherwise the row is preserved as relationship-unverified.
    """

    issuer: str
    number: str
    amount: Decimal | None
    amount_raw: str
    currency: str | None
    transaction_date: date | None
    is_credit_note: bool = False
    is_reversal: bool = False
    reference_number: str | None = None
    provenance: InvoiceProvenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.issuer, str) or not isinstance(self.number, str):
            raise TypeError("issuer and number must be text (identifiers stay strings)")
        if not isinstance(self.amount_raw, str):
            raise TypeError("amount_raw must be text (original source value)")
        if self.amount is not None and not isinstance(self.amount, Decimal):
            raise TypeError(
                f"amount must be Decimal, got {type(self.amount).__name__}; "
                "float/int input is rejected (no binary-float path)"
            )
        if self.amount is not None and (self.amount.is_nan() or self.amount.is_infinite()):
            raise ValueError("non-finite amount rejected")
        if self.currency is not None:
            normalized = self.currency.strip().upper()
            if not _CURRENCY_RE.match(normalized):
                raise ValueError(f"currency must be an explicit 3-letter code, got {self.currency!r}")
            object.__setattr__(self, "currency", normalized)
        if not isinstance(self.is_credit_note, bool) or not isinstance(self.is_reversal, bool):
            raise TypeError("is_credit_note/is_reversal must be bool")
        if self.reference_number is not None:
            if not isinstance(self.reference_number, str):
                raise TypeError("reference_number must be text (original-document reference)")
            if not self.reference_number.strip():
                object.__setattr__(self, "reference_number", None)
        if self.provenance is not None and not isinstance(self.provenance, InvoiceProvenance):
            raise TypeError("provenance must be InvoiceProvenance")

    def key(self) -> tuple[str, str]:
        """Issuer + number identity (never number alone). Surrounding
        whitespace is insignificant; letter case is folded; leading zeros and
        all other characters are significant."""
        return (self.issuer.strip().casefold(), self.number.strip())


@dataclass(frozen=True)
class ReconcileRequest:
    """Explicit run scope. Nothing is inferred: tolerance defaults to exact
    (zero), jurisdiction/tenant/datasets/period are caller-supplied labels
    carried into evidence and fingerprints for future wiring."""

    tenant_id: str
    sales_dataset_id: str
    jofo_dataset_id: str
    jurisdiction: str
    tolerance: Decimal = Decimal("0")
    rules_version: str = "1"
    period_start: date | None = None
    period_end: date | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("tenant_id", self.tenant_id),
            ("sales_dataset_id", self.sales_dataset_id),
            ("jofo_dataset_id", self.jofo_dataset_id),
            ("jurisdiction", self.jurisdiction),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be a non-blank string")
        if not isinstance(self.tolerance, Decimal):
            raise TypeError("tolerance must be Decimal (no float thresholds)")
        if self.tolerance < 0:
            raise ValueError("tolerance must be >= 0 (negative tolerance is meaningless)")
        if self.tolerance.is_nan() or self.tolerance.is_infinite():
            raise ValueError("non-finite tolerance rejected")


@dataclass(frozen=True)
class MatchOutcome:
    """One deterministic reconciliation outcome with evidence.

    ``sales``/``jofo`` hold the involved rows (empty when one-sided).
    ``delta`` is sales − JoFotara in exact Decimal where comparable, else None
    (never across currencies). ``rationale`` carries stable machine codes;
    ``flags`` carries warnings (WITHIN_TOLERANCE, period position, linkage).
    Language is factual (possible-issue phrasing); never fraud or legal
    violation assertions.
    """

    kind: str
    rule: str
    sales: tuple[CanonicalInvoice, ...] = field(default_factory=tuple)
    jofo: tuple[CanonicalInvoice, ...] = field(default_factory=tuple)
    delta: Decimal | None = None
    currency: str | None = None
    rationale: tuple[str, ...] = field(default_factory=tuple)
    flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReconciliationReport:
    """Deterministic, fingerprinted run result (stable under input reorder)."""

    tenant_id: str
    sales_dataset_id: str
    jofo_dataset_id: str
    jurisdiction: str
    rules_version: str
    tolerance: Decimal
    period_start: date | None
    period_end: date | None
    outcomes: tuple[MatchOutcome, ...]
    counts: dict[str, int]
    sales_total: int
    jofo_total: int
    fingerprint: str


def rule_for(kind: str, jurisdiction: str, rules_version: str) -> str:
    """Evidence rule reference, e.g. ``JO/REC-001/1`` (informational NOTE kind
    for linked/insufficient rows that no REC rule owns)."""
    return f"{jurisdiction}/{_RULE_BY_KIND[kind]}/{rules_version}"
