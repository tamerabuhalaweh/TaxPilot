"""EP-05A mapping & normalization core (deterministic, pure, side-effect-free).

Pipeline position: File Upload -> Extraction -> **this engine** -> Financial
Reconciliation -> Findings -> Reports. This package owns the middle stage only:
it consumes already-extracted headers/rows (never files) and emits typed
canonical rows with full source provenance, validation diagnostics, readiness
gating, deterministic fingerprints, and a versioned mapping contract.

SRS traceability (Master SRS v2.0; specified here, integration later):
FR-EXT-001 provenance via ``SourceLocation``; FR-EXT-002 suggestions never
authoritative + explicit ``ConfirmedMapping.confirmed`` gate; FR-EXT-003
raw/mapped/normalized preview; FR-EXT-004 ambiguous dates/separators/
currencies flagged, never inferred; FR-EXT-005 unrecognized numerics become
field errors, never zero; FR-EXT-006 preview + ``READY_FOR_CHECKS`` gate;
FR-EXT-007 stable fingerprints + source identity, reruns reproducible;
FR-EXT-008 valid/warning/failed counts reconcile; FR-EXT-010 versioned
``MappingProfile`` + drift/reconfirm (no persistence); FR-FIN-001 exact
``app.finance`` Decimal core incl. hostile contexts; FR-FIN-007 segregated
per-(field, currency) totals, no FX; FR-MAP-TIME-001 durations-only timings.

JoFotara boundary: ``jofotara_export`` is recognized as a document type but
refused without an explicitly approved format profile (``UNSUPPORTED_PROFILE``);
no government layouts, rates, versions, or support claims are invented here.

Totals cover eligible (VALID/WARNING) rows only; FAILED rows are excluded
and counted in ``excluded_rows``, so totals are never full-period figures
when rows were excluded. A general-ledger row is VALID only with at least
one valid monetary value. The numeric convention has no default and must be
opted into per run; header fingerprints use canonical JSON arrays so
delimiter collisions cannot hide schema drift.

No database, HTTP, network, file I/O, or external services. No tax rules,
no REC-001..005, no reports.
"""

from app.normalization.contracts import (
    GENERAL_LEDGER,
    JOFOTARA_EXPORT,
    SALES_REGISTER,
    ConfirmedMapping,
    DatasetResult,
    DriftReport,
    ExtractedRow,
    ExtractedSheet,
    FieldIssue,
    FieldTotal,
    MappingProfile,
    MappingRevision,
    NormalizationOptions,
    NormalizedField,
    NormalizedRow,
    RowCounts,
    SourceDocument,
    SourceLocation,
)
from app.normalization.dates import DATE_FORMATS, parse_strict_date
from app.normalization.engine import normalize_dataset
from app.normalization.mapping import (
    MappingIssue,
    MappingReport,
    build_profile,
    detect_drift,
    fingerprint_headers,
    validate_mapping,
)
from app.normalization.suggest import HeaderSuggestion, normalize_header, suggest_mapping

__all__ = [
    "DATE_FORMATS",
    "GENERAL_LEDGER",
    "JOFOTARA_EXPORT",
    "SALES_REGISTER",
    "ConfirmedMapping",
    "DatasetResult",
    "DriftReport",
    "ExtractedRow",
    "ExtractedSheet",
    "FieldIssue",
    "FieldTotal",
    "HeaderSuggestion",
    "MappingIssue",
    "MappingProfile",
    "MappingReport",
    "MappingRevision",
    "NormalizationOptions",
    "NormalizedField",
    "NormalizedRow",
    "RowCounts",
    "SourceDocument",
    "SourceLocation",
    "build_profile",
    "detect_drift",
    "fingerprint_headers",
    "normalize_dataset",
    "normalize_header",
    "parse_strict_date",
    "suggest_mapping",
    "validate_mapping",
]
