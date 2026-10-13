"""EP-04A extraction contracts (immutable, typed, pure data).

Limit defaults carry evidence: 25 MiB/file, 100k rows, 200 columns per Master
SRS v2.0 §12 (configurable); 32,767 cell chars is the Excel cell-text limit;
ZIP caps bound single archives an accountant could plausibly upload while
stopping decompression bombs. Callers handling larger books pass explicit
``ExtractionLimits`` instead of relying on bigger silent defaults.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.normalization import ExtractedSheet, SourceDocument

_MIB = 1024 * 1024


@dataclass(frozen=True)
class ExtractionLimits:
    """Hard bounds checked before and during parsing (fail-closed)."""

    max_file_bytes: int = 25 * _MIB
    max_rows: int = 100_000
    max_columns: int = 200
    max_cell_chars: int = 32767
    max_uncompressed_bytes: int = 256 * _MIB
    max_compression_ratio: float = 200.0
    max_zip_members: int = 256


@dataclass(frozen=True)
class CsvSettings:
    """Explicit CSV dialect. The delimiter is caller-selected, never sniffed."""

    delimiter: str
    header_row: int = 1


@dataclass(frozen=True)
class XlsxSettings:
    """Explicit XLSX selection. Exactly one of sheet name/index is required.

    ``allow_typed_cells`` is an explicit opt-in: by default any non-empty
    numeric/date/boolean cell fails closed (TYPED_CELLS) because Excel display
    formatting can change meaning; opted-in cells convert deterministically
    (integers/floats via exact repr, booleans TRUE/FALSE, datetimes ISO) and
    still require downstream review. Formula and error cells always fail.
    """

    sheet_name: str | None = None
    sheet_index: int | None = None
    header_row: int = 1
    allow_typed_cells: bool = False


@dataclass(frozen=True)
class ExtractionStats:
    """Structural counters only; never cell contents (no PII in telemetry)."""

    declared_format: str
    file_bytes: int
    worksheet: str
    header_row: int
    header_count: int
    data_rows: int
    skipped_blank_rows: int
    physical_rows_scanned: int


@dataclass(frozen=True)
class ExtractionResult:
    """Bounded extraction outcome ready for ``normalize_dataset``."""

    doc: SourceDocument
    sheet: ExtractedSheet
    stats: ExtractionStats


class ExtractionError(ValueError):
    """Typed extraction failure: {code} + actionable message, never values."""

    def __init__(self, message: str, *, code: str, detail: dict[str, object] | None = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.detail: dict[str, object] = dict(detail) if detail else {}
