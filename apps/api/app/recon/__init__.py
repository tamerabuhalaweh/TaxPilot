"""REC-001..004 sales↔JoFotara deterministic matching (pure domain).

Pipeline position: normalized datasets (EP-05A) -> **this engine** ->
findings review (EP-10) -> bilingual reports (EP-11). Consumes CanonicalInvoice
rows (via the sales adapter or explicit synthetic JoFotara fixtures) and emits
a fingerprinted ReconciliationReport with evidence-linked outcomes. No
persistence, API, LLM, tax interpretation, or fraud assertions.

SRS traceability (Master SRS v2.0 §7; specified behavior, integration later):
REC-001/002 unmatched presence, REC-003 exact-Decimal differences with
explicit tolerance, REC-004 deterministic duplicate clusters. REC-005 (GL),
multi-field net/tax/gross, review decisions, and reports are later slices.
"""

from app.recon.adapters import SkippedRow, sales_invoices_from_normalized
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
    InvoiceProvenance,
    MatchOutcome,
    ReconcileRequest,
    ReconciliationReport,
    rule_for,
)
from app.recon.matching import reconcile

__all__ = [
    "AMBIGUOUS",
    "AMOUNT_MISMATCH",
    "CREDIT_NOTE_LINKED",
    "DUPLICATE_JOFOTARA",
    "DUPLICATE_SALES",
    "EXACT_MATCH",
    "INSUFFICIENT_DATA",
    "REVERSAL_NOTED",
    "UNMATCHED_JOFOTARA",
    "UNMATCHED_SALES",
    "CanonicalInvoice",
    "InvoiceProvenance",
    "MatchOutcome",
    "ReconcileRequest",
    "ReconciliationReport",
    "SkippedRow",
    "reconcile",
    "rule_for",
    "sales_invoices_from_normalized",
]
