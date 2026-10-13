"""Strict bounded CSV extraction (UTF-8 only, explicit delimiter, no coercion).

``header_row`` is a physical line number: the header is the record starting
exactly on that line. A header line splitting a quoted multiline record is
refused rather than misaligned. Limits are enforced during streaming
iteration so oversized inputs fail before unbounded materialization.
"""

from __future__ import annotations

import csv
import hashlib
import io

from app.extraction.contracts import (
    CsvSettings,
    ExtractionError,
    ExtractionLimits,
    ExtractionResult,
    ExtractionStats,
)
from app.extraction.guards import check_bytes, check_doc_id, check_header_row
from app.normalization import ExtractedRow, ExtractedSheet, SourceDocument

_CSV_DELIMITERS = (",", ";", "\t", "|")
_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0"


def extract_csv(
    data: bytes,
    *,
    doc_id: str,
    settings: CsvSettings,
    limits: ExtractionLimits | None = None,
) -> ExtractionResult:
    """Extract a CSV document into ``ExtractedSheet`` + ``SourceDocument``.

    Raises :class:`ExtractionError` for oversized, mis-encoded, mis-shaped,
    or mis-declared inputs. Cells stay verbatim strings (leading zeros kept);
    physically blank lines are skipped with position preserved.
    """
    lim = limits or ExtractionLimits()
    doc_id = check_doc_id(doc_id)
    if not isinstance(settings, CsvSettings):
        raise TypeError(f"settings must be CsvSettings, got {type(settings).__name__}")
    check_bytes(data, lim)
    if data[:4] == _ZIP_MAGIC:
        raise ExtractionError(
            "declared csv but content has a ZIP/XLSX signature; refusing to misparse",
            code="FORMAT_MISMATCH",
        )
    if data[:8] == _OLE_MAGIC:
        raise ExtractionError(
            "declared csv but content has an OLE/legacy-Excel signature",
            code="FORMAT_MISMATCH",
        )
    if settings.delimiter not in _CSV_DELIMITERS:
        raise ExtractionError(
            f"delimiter must be one of {list(_CSV_DELIMITERS)} (explicitly selected), "
            f"got {settings.delimiter!r}",
            code="INVALID_DELIMITER",
        )
    header_row = check_header_row(settings.header_row)
    try:
        text = data.decode("utf-8-sig")  # BOM accepted, plain UTF-8 identical
    except UnicodeDecodeError as exc:
        raise ExtractionError(
            "CSV must be UTF-8 (BOM optional); decoding failed with no fallback applied",
            code="MALFORMED_ENCODING",
        ) from exc

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=settings.delimiter, strict=True)
    header: list[str] | None = None
    width = 0
    rows: list[ExtractedRow] = []
    skipped = 0
    scanned = 0
    previous_end = 0
    try:
        for record in reader:
            end = reader.line_num
            start = previous_end + 1
            previous_end = end
            if end < header_row:
                continue  # preamble record ends before the header line
            if start > header_row:
                if header is None:  # defensive: every line belongs to some record
                    raise ExtractionError(
                        f"header_row {header_row} holds no record",
                        code="HEADER_ROW_MISSING",
                    )
                scanned += 1
                if scanned > lim.max_rows:
                    raise ExtractionError(
                        f"more than {lim.max_rows} data rows",
                        code="TOO_MANY_ROWS",
                        detail={"scanned": scanned},
                    )
                normalized = _data_row(record, start, width, lim)
                if normalized is None:
                    skipped += 1
                else:
                    rows.append(normalized)
                continue
            if start < header_row:
                raise ExtractionError(
                    f"header_row {header_row} splits a quoted multiline record "
                    f"starting at line {start}; refusing to misalign columns",
                    code="HEADER_ROW_SPLIT",
                    detail={"row_number": start},
                )
            header = record
            width = _check_header(header, lim)
    except csv.Error as exc:
        raise ExtractionError(f"malformed CSV quoting/structure: {exc}", code="MALFORMED_CSV") from exc

    if header is None:
        raise ExtractionError(
            f"header_row {header_row} beyond the file contents",
            code="HEADER_ROW_MISSING",
        )
    digest = hashlib.sha256(data).hexdigest()
    sheet = ExtractedSheet(headers=tuple(header), rows=tuple(rows))
    return ExtractionResult(
        doc=SourceDocument(doc_id=doc_id, content_hash=digest, worksheet="CSV"),
        sheet=sheet,
        stats=ExtractionStats(
            declared_format="csv",
            file_bytes=len(data),
            worksheet="CSV",
            header_row=header_row,
            header_count=width,
            data_rows=len(rows),
            skipped_blank_rows=skipped,
            physical_rows_scanned=scanned,
        ),
    )


def _check_header(header: list[str], lim: ExtractionLimits) -> int:
    if not header or all(cell.strip() == "" for cell in header):
        raise ExtractionError("header row carries no column names", code="EMPTY_HEADERS")
    if len(header) > lim.max_columns:
        raise ExtractionError(
            f"{len(header)} columns exceeds {lim.max_columns}",
            code="TOO_MANY_COLUMNS",
            detail={"columns": len(header)},
        )
    for index, name in enumerate(header):
        if name.strip() == "":
            raise ExtractionError(
                f"blank header at column {index}",
                code="BLANK_HEADER",
                detail={"column_index": index},
            )
        if len(name) > lim.max_cell_chars:
            raise ExtractionError(
                f"header at column {index} exceeds {lim.max_cell_chars} chars",
                code="CELL_TOO_LARGE",
                detail={"column_index": index},
            )
    return len(header)


def _data_row(record: list[str], start_line: int, width: int, lim: ExtractionLimits) -> ExtractedRow | None:
    """Normalize one data record; None when physically blank (skip, keep gap)."""
    trimmed = list(record)
    while trimmed and trimmed[-1].strip() == "":
        trimmed.pop()
    if not trimmed:
        return None
    if len(trimmed) > width:
        raise ExtractionError(
            f"row {start_line} has {len(trimmed)} cells for {width} headers; "
            "kept as an error, never realigned by guessing",
            code="RAGGED_ROW",
            detail={"row_number": start_line},
        )
    while len(trimmed) < width:
        trimmed.append("")
    for index, cell in enumerate(trimmed):
        if len(cell) > lim.max_cell_chars:
            raise ExtractionError(
                f"row {start_line} column {index} exceeds {lim.max_cell_chars} chars",
                code="CELL_TOO_LARGE",
                detail={"row_number": start_line, "column_index": index},
            )
    return ExtractedRow(row_number=start_line, cells=tuple(trimmed))
