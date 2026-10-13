"""EP-05A mapping & normalization contracts (immutable, typed, pure data).

SRS mapping (Master SRS v2.0, all specified-not-implemented until integrated):
- FR-EXT-001: :class:`SourceLocation` carries document identity/hash,
  worksheet, row, column, and header for every normalized value.
- FR-EXT-002: :class:`ConfirmedMapping` requires explicit confirmation;
  suggestions (see ``suggest``) are never authoritative.
- FR-EXT-007/010: :class:`MappingProfile` + header fingerprints version
  reusable mappings and detect drift (no persistence here).
- FR-MAP-TIME-001: timings model carries durations only, never amounts.

No I/O, DB, network, or float anywhere in this package.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType

SALES_REGISTER = "sales_register"
GENERAL_LEDGER = "general_ledger"
JOFOTARA_EXPORT = "jofotara_export"
KNOWN_DOCUMENT_TYPES = (SALES_REGISTER, GENERAL_LEDGER, JOFOTARA_EXPORT)

READY_FOR_CHECKS = "READY_FOR_CHECKS"
NOT_READY = "NOT_READY"

STATUS_VALID = "VALID"
STATUS_WARNING = "WARNING"
STATUS_FAILED = "FAILED"

SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"

DRIFT_CURRENT = "CURRENT"
DRIFT_CHANGED = "DRIFT"

# Canonical fields per document type. Money fields hold exact Decimals,
# identifiers stay strings (leading zeros preserved), dates stay dates.
SALES_FIELDS = (
    "invoice_number",
    "transaction_date",
    "net_amount",
    "tax_amount",
    "gross_amount",
    "currency",
    "description",
)
SALES_REQUIRED = ("invoice_number", "transaction_date", "net_amount")
GL_FIELDS = (
    "account_code",
    "transaction_date",
    "debit_amount",
    "credit_amount",
    "currency",
    "description",
)
GL_REQUIRED = ("account_code", "transaction_date")
GL_AMOUNT_FIELDS = ("debit_amount", "credit_amount")

FIELD_KIND = {
    "invoice_number": "IDENTIFIER",
    "account_code": "IDENTIFIER",
    "transaction_date": "DATE",
    "net_amount": "MONEY",
    "tax_amount": "MONEY",
    "gross_amount": "MONEY",
    "debit_amount": "MONEY",
    "credit_amount": "MONEY",
    "currency": "CURRENCY",
    "description": "TEXT",
}

FIELDS_BY_DOCUMENT = {
    SALES_REGISTER: SALES_FIELDS,
    GENERAL_LEDGER: GL_FIELDS,
}
REQUIRED_BY_DOCUMENT = {
    SALES_REGISTER: SALES_REQUIRED,
    GENERAL_LEDGER: GL_REQUIRED,
}


@dataclass(frozen=True)
class SourceDocument:
    """Identity of the extracted source file (traceability anchor)."""

    doc_id: str
    content_hash: str
    worksheet: str = "Sheet1"


@dataclass(frozen=True)
class ExtractedRow:
    """One raw spreadsheet row. ``row_number`` is the original sheet row
    (header is normally row 1, so the first data row is 2)."""

    row_number: int
    cells: tuple[str, ...]


@dataclass(frozen=True)
class ExtractedSheet:
    """Headers plus data rows exactly as extracted (no interpretation)."""

    headers: tuple[str, ...]
    rows: tuple[ExtractedRow, ...]


@dataclass(frozen=True)
class ConfirmedMapping:
    """Caller-confirmed canonical-field -> source-header map.

    ``confirmed`` MUST be True for any dataset to become READY_FOR_CHECKS;
    suggestions alone never satisfy the gate. ``mapping_version`` is an opaque
    caller-owned version string bound into the dataset fingerprint. The map is
    snapshotted and frozen at construction: later caller-side mutations of the
    passed dict cannot alter an approved mapping.
    """

    field_map: Mapping[str, str]
    confirmed: bool
    mapping_version: str = "1"
    approved_by: str = ""
    approved_at: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.field_map, Mapping):
            raise TypeError(f"field_map must be a mapping, got {type(self.field_map).__name__}")
        object.__setattr__(self, "field_map", MappingProxyType(dict(self.field_map)))


@dataclass(frozen=True)
class NormalizationOptions:
    """Explicit per-run profiles. Nothing is inferred.

    ``date_format`` is a key of ``DATE_FORMATS`` (``None`` means the caller
    selected nothing: every date stays unresolved). ``default_currency`` is an
    explicitly approved 3-letter code used only when no currency column is
    mapped (``None`` means no approval: missing currency blocks). Period
    bounds are inclusive; out-of-range dates warn, never drop. ``doc_type``
    selects the schema contract explicitly (never inferred from headers).
    The numeric convention (``decimal_separator``/``grouping_separator``) has
    no default: the caller must opt into it on every run.
    """

    doc_type: str
    decimal_separator: str
    grouping_separator: str | None
    date_format: str | None = None
    default_currency: str | None = None
    period_start: date | None = None
    period_end: date | None = None


@dataclass(frozen=True)
class MappingProfile:
    """Versioned reusable mapping contract (persisted later, not here).

    ``tenant_id``/``client_id`` bind the profile to its owner scope; this
    module performs no authorization, it only carries and fingerprints them.
    The map is snapshotted and frozen at construction like ``ConfirmedMapping``.
    """

    profile_id: str
    tenant_id: str
    client_id: str
    doc_type: str
    header_fingerprint: str
    field_map: Mapping[str, str]
    mapping_version: str
    approved_by: str = ""
    approved_at: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.field_map, Mapping):
            raise TypeError(f"field_map must be a mapping, got {type(self.field_map).__name__}")
        object.__setattr__(self, "field_map", MappingProxyType(dict(self.field_map)))


@dataclass(frozen=True)
class SourceLocation:
    """Exact origin of one normalized value (FR-EXT-001)."""

    doc_id: str
    content_hash: str
    worksheet: str
    row_number: int
    column_index: int
    header: str


@dataclass(frozen=True)
class FieldIssue:
    """One validation diagnostic: blocking ERROR or non-blocking WARNING."""

    code: str
    message: str
    severity: str  # ERROR | WARNING
    location: SourceLocation | None = None


@dataclass(frozen=True)
class NormalizedField:
    """One canonical field value with provenance and diagnostics."""

    canonical: str
    raw: str
    normalized: Decimal | date | str | None
    currency: str | None
    location: SourceLocation
    issues: tuple[FieldIssue, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NormalizedRow:
    """One normalized spreadsheet row; FAILED = at least one ERROR issue."""

    row_number: int
    status: str  # VALID | WARNING | FAILED
    fields: tuple[NormalizedField, ...] = field(default_factory=tuple)
    row_issues: tuple[FieldIssue, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FieldTotal:
    """Segregated per-(field, currency) total over eligible rows only.

    Currencies never combine. Totals cover VALID + WARNING rows; FAILED rows
    are excluded (see ``DatasetResult.eligible_rows``/``excluded_rows``), so a
    total is never mistaken for a full-period figure when rows were excluded.
    """

    field: str
    currency: str
    total: Decimal


@dataclass(frozen=True)
class MappingRevision:
    """Mapping identity bound into the dataset fingerprint."""

    mapping_version: str
    header_fingerprint: str
    approved_by: str


@dataclass(frozen=True)
class DriftReport:
    """Result of comparing saved profile headers against current headers."""

    status: str  # CURRENT | DRIFT
    added: tuple[str, ...] = field(default_factory=tuple)
    removed: tuple[str, ...] = field(default_factory=tuple)
    requires_reconfirmation: bool = False
    message: str = ""


@dataclass(frozen=True)
class RowCounts:
    """Valid + warning + failed always reconciles to total."""

    total: int
    valid: int
    warning: int
    failed: int


@dataclass(frozen=True)
class DatasetResult:
    """Deterministic normalization outcome with preview and readiness.

    ``eligible_rows`` (VALID + WARNING) contribute to ``totals``;
    ``excluded_rows`` (FAILED) never do. ``timings_ms`` is observational
    metadata (live clock) and is excluded from ``fingerprint``: equal inputs
    rerun to equal fingerprints and rows even as timings vary.
    """

    doc_type: str
    readiness: str  # READY_FOR_CHECKS | NOT_READY
    rows: tuple[NormalizedRow, ...]
    preview: tuple[NormalizedRow, ...]  # first <=20 rows, same objects
    counts: RowCounts
    eligible_rows: int
    excluded_rows: int
    blocking_issues: tuple[FieldIssue, ...]
    warnings: tuple[FieldIssue, ...]
    totals: tuple[FieldTotal, ...]
    fingerprint: str
    mapping_revision: MappingRevision
    timings_ms: dict[str, float]
