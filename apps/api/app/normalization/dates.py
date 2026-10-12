"""Strict calendar-date parsing with explicitly selected formats.

Numeric dates such as ``01/02/2026`` are never interpreted without an
explicitly supplied format: DMY and MDY read them differently and guessing
would fabricate evidence. Invalid calendar dates are rejected; callers decide
period handling (flag, never drop).
"""

from __future__ import annotations

from datetime import date, datetime

DATE_FORMATS = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
    "DD-MM-YYYY": "%d-%m-%Y",
    "YYYY/MM/DD": "%Y/%m/%d",
    "DD.MM.YYYY": "%d.%m.%Y",
}


def parse_strict_date(raw: str, date_format: str) -> date:
    """Parse ``raw`` with exactly ``date_format`` (a key of DATE_FORMATS).

    Raises ``ValueError`` for unknown formats (caller config error) and for
    values that do not match, including impossible calendar dates.
    """
    pattern = DATE_FORMATS.get(date_format)
    if pattern is None:
        raise ValueError(f"unknown date_format {date_format!r}; choose one of {sorted(DATE_FORMATS)}")
    text = raw.strip()
    if text == "":
        raise ValueError("blank date")
    try:
        parsed = datetime.strptime(text, pattern).date()
    except ValueError as exc:
        raise ValueError(f"{raw!r} does not match {date_format}: {exc}") from exc
    if parsed.year < 1000:
        raise ValueError(f"{raw!r} requires a four-digit year for {date_format}")
    return parsed
