"""Bounded bytes/stream entry points (explicit format, never sniffed alone)."""

from __future__ import annotations

from typing import BinaryIO

from app.extraction.contracts import (
    CsvSettings,
    ExtractionLimits,
    ExtractionResult,
    XlsxSettings,
)
from app.extraction.csv_reader import extract_csv
from app.extraction.guards import check_doc_id
from app.extraction.xlsx_reader import extract_xlsx


def extract_bytes(
    data: bytes,
    *,
    declared_format: str,
    doc_id: str,
    csv: CsvSettings | None = None,
    xlsx: XlsxSettings | None = None,
    limits: ExtractionLimits | None = None,
) -> ExtractionResult:
    """Extract ``data`` per ``declared_format`` (``"csv"`` or ``"xlsx"``).

    The matching settings object is required (CSV needs ``csv=``, XLSX needs
    ``xlsx=``); signatures are still verified secondarily so a mis-declared
    file fails instead of misparsing.
    """
    from app.extraction.contracts import ExtractionError

    doc_id = check_doc_id(doc_id)
    if declared_format == "csv":
        if csv is None or xlsx is not None:
            raise ExtractionError(
                "declared csv requires csv= settings and no xlsx= settings",
                code="SETTINGS_MISMATCH",
            )
        return extract_csv(data, doc_id=doc_id, settings=csv, limits=limits)
    if declared_format == "xlsx":
        if xlsx is None or csv is not None:
            raise ExtractionError(
                "declared xlsx requires xlsx= settings and no csv= settings",
                code="SETTINGS_MISMATCH",
            )
        return extract_xlsx(data, doc_id=doc_id, settings=xlsx, limits=limits)
    raise ExtractionError(
        f"declared_format must be 'csv' or 'xlsx', got {declared_format!r}",
        code="UNSUPPORTED_FORMAT",
    )


def extract_stream(
    stream: BinaryIO,
    *,
    declared_format: str,
    doc_id: str,
    csv: CsvSettings | None = None,
    xlsx: XlsxSettings | None = None,
    limits: ExtractionLimits | None = None,
) -> ExtractionResult:
    """Read at most ``max_file_bytes + 1`` from ``stream``, then extract.

    The stream is never consumed unboundedly: one byte past the cap aborts
    with FILE_TOO_LARGE before parsing starts.
    """
    from app.extraction.contracts import ExtractionError

    lim = limits or ExtractionLimits()
    if not hasattr(stream, "read"):
        raise TypeError(f"stream must be a binary stream, got {type(stream).__name__}")
    chunks: list[bytes] = []
    remaining = lim.max_file_bytes + 1
    while remaining > 0:
        piece = stream.read(min(1024 * 1024, remaining))
        if not piece:
            break
        if not isinstance(piece, bytes | bytearray):
            raise TypeError("stream must yield bytes")
        chunks.append(bytes(piece))
        remaining -= len(piece)
    data = b"".join(chunks)
    if len(data) > lim.max_file_bytes:
        raise ExtractionError(f"stream exceeds {lim.max_file_bytes} bytes", code="FILE_TOO_LARGE")
    return extract_bytes(data, declared_format=declared_format, doc_id=doc_id, csv=csv, xlsx=xlsx, limits=lim)
