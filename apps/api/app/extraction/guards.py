"""Shared input guards for extraction (fail-closed, no content inspection)."""

from __future__ import annotations

from app.extraction.contracts import ExtractionError, ExtractionLimits


def check_bytes(data: bytes, limits: ExtractionLimits) -> None:
    if not isinstance(data, bytes):
        raise TypeError(f"data must be bytes, got {type(data).__name__}")
    if len(data) > limits.max_file_bytes:
        raise ExtractionError(
            f"file too large: {len(data)} bytes exceeds {limits.max_file_bytes}",
            code="FILE_TOO_LARGE",
            detail={"file_bytes": len(data), "max_file_bytes": limits.max_file_bytes},
        )
    if not data:
        raise ExtractionError("empty file: no bytes to extract", code="EMPTY_FILE")


def check_doc_id(doc_id: object) -> str:
    if not isinstance(doc_id, str) or not doc_id.strip():
        raise ExtractionError("doc_id must be a non-blank string", code="INVALID_DOC_ID")
    return doc_id


def check_header_row(header_row: object) -> int:
    if not isinstance(header_row, int) or isinstance(header_row, bool) or header_row < 1:
        raise ExtractionError(
            f"header_row must be a 1-based int, got {header_row!r}",
            code="INVALID_HEADER_ROW",
        )
    return header_row
