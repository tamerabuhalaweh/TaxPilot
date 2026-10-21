"""Minimal, dependency-free PDF writer for the synthetic demo report.

Deliberately tiny and self-contained so REC-UI-01 can emit a verifiable,
deterministic document without adding a runtime dependency (the repo has no
PDF library and the security gate audits the pinned requirement set). Output
uses the core Helvetica/Courier fonts under WinAnsi encoding and therefore
carries ASCII text only: non-ASCII characters are replaced with '?'. The
demo report is intentionally English-only here; the bilingual experience lives
in the web UI. This is not a general-purpose PDF library.

REC-UI-02 adds two presentation guarantees: long text is wrapped before
pagination (so a long finding sentence can never run off the page), and an
optional footer carries a repeated note plus ``Page X of Y``.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

_PAGE_W = 595
_PAGE_H = 842
_MARGIN = 40
_LINE_H = 14
_TOP = _PAGE_H - _MARGIN
_BOTTOM = _MARGIN
_FOOTER_GAP = 26

# Approximate advance widths (fraction of font size) for the core fonts. Exact
# metrics are unnecessary: the goal is to stop text leaving the printable area,
# not to typeset a book.
_ADVANCE = {"F1": 0.52, "F2": 0.6}


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


def _text_width(text: str, line: Line) -> float:
    return len(text) * line.size * _ADVANCE.get(line.font, 0.52)


def _max_chars(line: Line) -> int:
    usable = _PAGE_W - 2 * _MARGIN - 6
    return max(8, int(usable / (line.size * _ADVANCE.get(line.font, 0.52))))


def wrap_lines(lines: list[Line]) -> list[Line]:
    """Wrap every line to the printable width, preserving indentation."""
    wrapped: list[Line] = []
    for line in lines:
        text = line.text
        if not text.strip():
            wrapped.append(line)
            continue
        indent = text[: len(text) - len(text.lstrip())]
        width = max(8, _max_chars(line) - len(indent))
        chunks = textwrap.wrap(
            text.strip(),
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=True,
            drop_whitespace=True,
        ) or [""]
        for chunk in chunks:
            wrapped.append(Line(f"{indent}{chunk}", line.size, line.font))
    return wrapped


def _content_stream(lines: list[Line], footer: str | None, page: int, total: int) -> bytes:
    parts: list[str] = []
    y = _TOP
    for line in lines:
        parts.append(f"BT /{line.font} {line.size} Tf 1 0 0 1 {_MARGIN} {y} Tm ({_escape(line.text)}) Tj ET")
        y -= _LINE_H
    if footer is not None:
        rule_y = _BOTTOM + 14
        parts.append(f"0.7 w 0.6 G {_MARGIN} {rule_y} m {_PAGE_W - _MARGIN} {rule_y} l S")
        footer_line = Line(footer, size=8, font="F2")
        parts.append(
            f"BT /{footer_line.font} {footer_line.size} Tf 1 0 0 1 {_MARGIN} {_BOTTOM} Tm "
            f"({_escape(footer_line.text)}) Tj ET"
        )
        counter = Line(f"Page {page} of {total}", size=8, font="F1")
        x = _PAGE_W - _MARGIN - _text_width(counter.text, counter)
        parts.append(
            f"BT /{counter.font} {counter.size} Tf 1 0 0 1 {x:.1f} {_BOTTOM} Tm "
            f"({_escape(counter.text)}) Tj ET"
        )
    return ("\n".join(parts) + "\n").encode("latin-1")


def build_pdf(lines: list[Line], *, footer: str | None = None) -> bytes:
    """Serialize lines into a valid single- or multi-page PDF document."""
    prepared = wrap_lines(lines)
    top = _TOP if footer is None else _TOP - _FOOTER_GAP
    capacity = max(1, (top - _BOTTOM) // _LINE_H)
    pages = [prepared[i : i + capacity] for i in range(0, len(prepared), capacity)] or [[]]
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
        stream = _content_stream(page_lines, footer, index + 1, n_pages)
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


__all__ = ["Line", "build_pdf", "wrap_lines"]
