"""EP-04A bounded CSV/XLSX extraction adapter (deterministic, pure bytes in).

Position: bounded file bytes -> **this adapter** -> ``app.normalization``
``ExtractedSheet``/``SourceDocument`` -> ``normalize_dataset``. No uploads,
storage, APIs, or network; SHA-256 of the original bytes is the file identity
(caller hashes are never trusted).

Security matrix (fail-closed; messages carry coordinates/counts, never values):
25 MiB/file, 100k rows, 200 columns, 32,767 chars/cell, 256 MiB verified
decompressed ZIP total, 200:1 compression ratio, 256 members; UTF-8(-BOM)
only with no fallback; explicit delimiter/sheet/header selection; ZIP
signature + member allowlist (macros, embeddings, external links, encrypted
or oddly-compressed members refused); actual decompressed bytes re-verified
by streaming read (declared sizes are attacker-controlled); openpyxl
read-only, ``data_only=False`` so formulas surface and are refused with cached
values never trusted; typed numerics/dates refused unless explicitly opted in
(exact repr/ISO conversion, still review-gated); nothing executes, nothing
touches disk or network.

SRS traceability (Master SRS v2.0): FR-FILE-001/003/004/006/007 bounded
extraction + provenance; FR-EXT-001 exact worksheet/row/cell origins;
FR-JOF-001/002 unsupported formats fail closed (real JoFotara exports stay
``UNSUPPORTED_PROFILE`` downstream; no layouts invented here).
"""

from app.extraction.api import extract_bytes, extract_stream
from app.extraction.contracts import (
    CsvSettings,
    ExtractionError,
    ExtractionLimits,
    ExtractionResult,
    ExtractionStats,
    XlsxSettings,
)

__all__ = [
    "CsvSettings",
    "ExtractionError",
    "ExtractionLimits",
    "ExtractionResult",
    "ExtractionStats",
    "XlsxSettings",
    "extract_bytes",
    "extract_stream",
]
