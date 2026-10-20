"""Minimal, dependency-free PDF writer for the synthetic demo report.

Deliberately tiny and self-contained so REC-UI-01 can emit a verifiable,
deterministic document without adding a runtime dependency (the repo has no
PDF library and the security gate audits the pinned requirement set). Output
uses the core Helvetica/Courier fonts under WinAnsi encoding and therefore
carries ASCII text only: non-ASCII characters are replaced with '?'. The
demo report is intentionally English-only here; the bilingual experience lives
in the web UI. This is not a general-purpose PDF library.
"""

from __future__ import annotations

from dataclasses import dataclass

_PAGE_W = 595
_PAGE_H = 842
_MARGIN = 40
_LINE_H = 14
_TOP = _PAGE_H - _MARGIN
_BOTTOM = _MARGIN


@dataclass(frozen=True)
class Line:
    """One rendered text line (core font F1=Helvetica, F2=Courier)."""

    text: str
    size: int = 10
    font: str = "F1"


def _escape(text: str) -> str:
    out: list[str] = []
    for ch in text:
        if ch in "()\\":
            out.append("\\" + ch)
        elif 32 <= ord(ch) <= 126:
            out.append(ch)
        else:
            out.append("?")
    return "".join(out)


def _content_stream(lines: list[Line]) -> bytes:
    parts: list[str] = []
    y = _TOP
    for line in lines:
        parts.append(f"BT /{line.font} {line.size} Tf 1 0 0 1 {_MARGIN} {y} Tm ({_escape(line.text)}) Tj ET")
        y -= _LINE_H
    return ("\n".join(parts) + "\n").encode("latin-1")


def build_pdf(lines: list[Line]) -> bytes:
    """Serialize lines into a valid single- or multi-page PDF document."""
    capacity = max(1, (_TOP - _BOTTOM) // _LINE_H)
    pages = [lines[i : i + capacity] for i in range(0, len(lines), capacity)] or [[]]
    n_pages = len(pages)
    page_ids = [5 + 2 * i for i in range(n_pages)]

    objects: dict[int, bytes] = {}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode("latin-1")
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    objects[4] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"
    for index, page_lines in enumerate(pages):
        pid = page_ids[index]
        content_id = pid + 1
        objects[pid] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_W} {_PAGE_H}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("latin-1")
        stream = _content_stream(page_lines)
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"endstream"
        )

    max_id = max(objects)
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for oid in range(1, max_id + 1):
        offsets[oid] = len(out)
        out += f"{oid} 0 obj\n".encode("latin-1") + objects[oid] + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {max_id + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for oid in range(1, max_id + 1):
        out += f"{offsets[oid]:010d} 00000 n \n".encode("latin-1")
    out += f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("latin-1")
    return bytes(out)


__all__ = ["Line", "build_pdf"]
