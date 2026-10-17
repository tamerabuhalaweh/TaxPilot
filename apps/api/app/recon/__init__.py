"""REC-001..004 sales↔JoFotara deterministic matching (pure domain).

Pipeline position: normalized datasets (EP-05A) -> **this engine** ->
findings review (EP-10) -> bilingual reports (EP-11). Consumes CanonicalInvoice
rows (via the sales adapter or explicit synthetic JoFotara fixtures) and emits
a fingerprinted ReconciliationReport with evidence-linked outcomes. No
persistence, API, LLM, tax interpretation, or fraud assertions. The
``findings`` projection turns a report into accountant-facing review items
(read model only; decisions and persistence are later slices).

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
    InvoiceProvenance,
    MatchOutcome,
    ReconcileRequest,
    ReconciliationReport,
    rule_for,
)
from app.recon.eligibility import (
    ELIGIBLE,
    ENGAGEMENT_NOT_ACTIVE,
    MISSING_DATASET_VERSION,
    SOURCE_NOT_RELEASED,
    UNAPPROVED_MAPPING,
    UNCONFIRMED_JURISDICTION,
    UNSUPPORTED_JOFO_PROFILE,
    EligibilityDecision,
    EligibilitySnapshot,
    evaluate,
)
from app.recon.execution import (
    DEFAULT_RULES_VERSION,
    OPERATION,
    RunDescriptor,
    payload_hash,
    source_set_fingerprint,
)
from app.recon.findings import (
    EvidenceRef,
    FindingsReport,
    MoneyView,
    ReviewFinding,
    project,
)
from app.recon.matching import reconcile

__all__ = [
    "AMBIGUOUS",
    "AMOUNT_MISMATCH",
    "CREDIT_NOTE_LINKED",
    "CREDIT_NOTE_UNVERIFIED",
    "DEFAULT_RULES_VERSION",
    "DUPLICATE_JOFOTARA",
    "DUPLICATE_SALES",
    "ELIGIBLE",
    "ENGAGEMENT_NOT_ACTIVE",
    "EXACT_MATCH",
    "INSUFFICIENT_DATA",
    "MISSING_DATASET_VERSION",
    "OPERATION",
    "REVERSAL_NOTED",
    "REVERSAL_UNVERIFIED",
    "SOURCE_NOT_RELEASED",
    "UNAPPROVED_MAPPING",
    "UNCONFIRMED_JURISDICTION",
    "UNMATCHED_JOFOTARA",
    "UNMATCHED_SALES",
    "UNSUPPORTED_JOFO_PROFILE",
    "CanonicalInvoice",
    "EligibilityDecision",
    "EligibilitySnapshot",
    "EvidenceRef",
    "FindingsReport",
    "InvoiceProvenance",
    "MatchOutcome",
    "MoneyView",
    "ReconcileRequest",
    "ReconciliationReport",
    "ReviewFinding",
    "RunDescriptor",
    "SkippedRow",
    "evaluate",
    "payload_hash",
    "project",
    "reconcile",
    "rule_for",
    "sales_invoices_from_normalized",
    "source_set_fingerprint",
]
