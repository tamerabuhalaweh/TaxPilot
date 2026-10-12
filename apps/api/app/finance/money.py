"""FIN-CORE-01: strict exact-Decimal amount parser + currency-safe totals.

Normative: Master SRS v2.0 FR-FIN-001 (Decimal/NUMERIC + currency, no float
drift), FR-FIN-007 (segregated totals absent approved FX), FR-EXT-004/005
(invalid/ambiguous numerics flagged, never silent zero).

Pure, side-effect-free, stdlib-only. No API/DB/worker/UI imports. All
financial arithmetic uses :class:`decimal.Decimal` constructed from strings;
``float`` never appears on any path.

Contract:
- Caller supplies text + explicit :class:`ParseProfile` + explicit ISO-4217
  3-letter currency. No locale guessing, no default currency.
- Invalid/ambiguous/missing input raises :class:`MoneyParseError`
  (a ``ValueError``); never coerced to zero.
- Grouping is strictly validated (``12,34.56`` rejected for comma grouping).
- Exact precision/sign preserved; no FX, rounding, or quantization here.
- Aggregation segregates by currency; mixing raises or stays separated.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

MAX_RAW_LENGTH = 64
_DIGITS = frozenset("0123456789")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_NON_FINITE = frozenset({"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"})
# Common spreadsheet/placeholder tokens that must never become zero.
_PLACEHOLDERS = frozenset({"n/a", "na", "#n/a", "#value!", "null", "none", "nil", "?", "-", "--", "—", "–"})
_ALLOWED_GROUPING = frozenset({",", ".", " ", "'", "’", "\u00a0", "\u202f"})


class MoneyParseError(ValueError):
    """Typed validation failure for monetary parsing."""

    def __init__(self, message: str, *, code: str, raw: object = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.raw = raw


class CurrencyMismatchError(ValueError):
    """Raised when amounts of different currencies would be combined."""

    def __init__(self, message: str, *, expected: str, found: str) -> None:
        super().__init__(message)
        self.expected = expected
        self.found = found


@dataclass(frozen=True)
class ParseProfile:
    """Explicit number-shape profile supplied by the caller.

    ``decimal_separator`` is ``"."`` or ``","``. ``grouping_separator`` is
    ``None`` (no grouping allowed) or a single separator character that must
    differ from the decimal separator. There is no locale inference: the same
    text (e.g. ``"1,234"``) parses differently under different profiles.
    """

    decimal_separator: str
    grouping_separator: str | None = None

    def __post_init__(self) -> None:
        dec = self.decimal_separator
        grp = self.grouping_separator
        if dec not in (".", ","):
            raise ValueError("decimal_separator must be '.' or ','")
        if grp is not None:
            if not isinstance(grp, str) or len(grp) != 1:
                raise ValueError("grouping_separator must be None or a single character")
            if grp not in _ALLOWED_GROUPING:
                raise ValueError(f"unsupported grouping_separator: {grp!r}")
            if grp == dec:
                raise ValueError("decimal_separator and grouping_separator must differ")


@dataclass(frozen=True)
class ParsedMoney:
    """Parsed monetary value with source retained.

    ``raw`` is the exact caller-supplied text (unstripped). ``amount`` is the
    exact :class:`Decimal`; ``currency`` is the normalized 3-letter code.
    """

    raw: str
    amount: Decimal
    currency: str

    def __add__(self, other: object) -> ParsedMoney:
        if not isinstance(other, ParsedMoney):
            return NotImplemented  # type: ignore[return-value]
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"cannot add {self.currency} and {other.currency}",
                expected=self.currency,
                found=other.currency,
            )
        return ParsedMoney(
            raw=f"({self.raw})+({other.raw})",
            amount=self.amount + other.amount,
            currency=self.currency,
        )


def _normalize_currency(currency: object, raw: object) -> str:
    if not isinstance(currency, str):
        raise MoneyParseError("currency must be an explicit 3-letter code", code="invalid_currency", raw=raw)
    norm = currency.strip().upper()
    if not _CURRENCY_RE.match(norm):
        raise MoneyParseError(
            f"currency must be an explicit 3-letter code, got {currency!r}",
            code="invalid_currency",
            raw=raw,
        )
    return norm


def _check_profile(profile: object, raw: object) -> ParseProfile:
    if not isinstance(profile, ParseProfile):
        raise MoneyParseError(
            "a ParseProfile (decimal_separator + grouping_separator) is required; "
            "number shape is never inferred",
            code="invalid_profile",
            raw=raw,
        )
    return profile


def parse_amount(raw: object, *, currency: str, profile: ParseProfile) -> ParsedMoney:
    """Parse ``raw`` text into an exact :class:`Decimal` with currency.

    Fail-closed: blank, placeholders, non-finite tokens, wrong types
    (``float``/``int``/``None``/``Decimal``/``bytes``), embedded symbols,
    misplaced grouping, or multiple decimals all raise :class:`MoneyParseError`.
    """
    cur = _normalize_currency(currency, raw)
    prof = _check_profile(profile, raw)

    if not isinstance(raw, str):
        raise MoneyParseError(
            f"amount must be text, got {type(raw).__name__}; "
            "numeric float/int input is rejected (no binary-float path)",
            code="invalid_type",
            raw=raw,
        )
    if len(raw) > MAX_RAW_LENGTH:
        raise MoneyParseError(f"amount text exceeds {MAX_RAW_LENGTH} characters", code="too_long", raw=raw)

    text = raw.strip()
    if text == "":
        raise MoneyParseError("blank amount is not zero", code="blank", raw=raw)

    lowered = text.lower()
    if lowered in _NON_FINITE:
        raise MoneyParseError(f"non-finite value {raw!r} rejected", code="non_finite", raw=raw)
    if lowered in _PLACEHOLDERS:
        raise MoneyParseError(
            f"placeholder {raw!r} is not zero and has no numeric meaning",
            code="placeholder",
            raw=raw,
        )

    # Normalize narrow-NBSP/NBSP to a plain space when space-grouping is used
    # (common in Excel exports); otherwise interior whitespace is rejected.
    dec = prof.decimal_separator
    grp = prof.grouping_separator
    if grp == " ":
        text = text.replace("\u00a0", " ").replace("\u202f", " ")
    elif grp == "\u00a0" or grp == "\u202f":
        grp = " "  # treat all space-likes uniformly; canonical form drops them
        text = text.replace("\u00a0", " ").replace("\u202f", " ")

    # Sign: single optional leading +/- only. Parentheses, trailing signs,
    # and DR/CR markers are rejected (no debit/credit interpretation).
    sign = ""
    body = text
    if body[0] in ("+", "-"):
        sign = body[0]
        body = body[1:]
        if body == "":
            raise MoneyParseError(f"lone sign in {raw!r}", code="invalid_format", raw=raw)
    if "+" in body or "-" in body or "(" in body or ")" in body:
        raise MoneyParseError(
            f"misplaced sign/bracket in {raw!r}; only one leading +/- is allowed",
            code="invalid_format",
            raw=raw,
        )

    # Character allowlist: ASCII digits + the two configured separators only.
    allowed = set("0123456789") | {dec} | ({grp} if grp is not None else set())
    for ch in body:
        if ch not in allowed:
            raise MoneyParseError(
                f"unsupported character {ch!r} in {raw!r}; "
                "currency symbols, letters, and spaces must not be embedded",
                code="invalid_character",
                raw=raw,
            )

    parts = body.split(dec)
    if len(parts) > 2:
        raise MoneyParseError(f"multiple decimal separators in {raw!r}", code="multiple_decimals", raw=raw)
    int_part = parts[0]
    frac_part: str | None = parts[1] if len(parts) == 2 else None

    if int_part == "" or (frac_part is not None and frac_part == ""):
        raise MoneyParseError(
            f"missing digits around decimal separator in {raw!r}",
            code="invalid_format",
            raw=raw,
        )
    if frac_part is not None and (grp is not None and grp in frac_part):
        raise MoneyParseError(
            f"grouping separator inside fraction in {raw!r}", code="invalid_grouping", raw=raw
        )
    if frac_part is not None and not _is_ascii_digits(frac_part):
        raise MoneyParseError(f"non-digit fraction in {raw!r}", code="invalid_format", raw=raw)

    if grp is None:
        if not _is_ascii_digits(int_part):
            raise MoneyParseError(f"invalid integer part in {raw!r}", code="invalid_format", raw=raw)
        digits_int = int_part
    else:
        if grp in int_part:
            _validate_grouped_integer(int_part, grp, raw)
            digits_int = int_part.replace(grp, "")
        else:
            if not _is_ascii_digits(int_part):
                raise MoneyParseError(f"invalid integer part in {raw!r}", code="invalid_format", raw=raw)
            digits_int = int_part

    canonical = sign + digits_int + ("." + frac_part if frac_part is not None else "")
    try:
        value = Decimal(canonical)
    except InvalidOperation as exc:
        raise MoneyParseError(f"unrecognized numeric value {raw!r}", code="invalid_number", raw=raw) from exc
    if value.is_nan() or value.is_infinite():
        raise MoneyParseError(f"non-finite value {raw!r} rejected", code="non_finite", raw=raw)
    return ParsedMoney(raw=raw, amount=value, currency=cur)


def _is_ascii_digits(s: str) -> bool:
    return len(s) > 0 and all(c in _DIGITS for c in s)


def _validate_grouped_integer(int_part: str, grp: str, raw: object) -> None:
    groups = int_part.split(grp)
    if any(g == "" for g in groups):
        raise MoneyParseError(f"misplaced grouping separator in {raw!r}", code="invalid_grouping", raw=raw)
    if not all(_is_ascii_digits(g) for g in groups):
        raise MoneyParseError(f"non-digit grouping in {raw!r}", code="invalid_grouping", raw=raw)
    if not 1 <= len(groups[0]) <= 3:
        raise MoneyParseError(
            f"leading group must be 1-3 digits in {raw!r}", code="invalid_grouping", raw=raw
        )
    for g in groups[1:]:
        if len(g) != 3:
            raise MoneyParseError(
                f"each grouped block after the first must be 3 digits in {raw!r}",
                code="invalid_grouping",
                raw=raw,
            )


def total_by_currency(items: Iterable[ParsedMoney]) -> dict[str, Decimal]:
    """Sum parsed amounts segregated by currency (pure; new dict each call).

    Never combines currencies. Empty input yields ``{}`` (not zero).
    """
    totals: dict[str, Decimal] = {}
    for item in items:
        if not isinstance(item, ParsedMoney):
            raise TypeError(f"total_by_currency expects ParsedMoney, got {type(item).__name__}")
        totals[item.currency] = totals.get(item.currency, Decimal("0")) + item.amount
    return totals


def sum_same_currency(items: Iterable[ParsedMoney], *, currency: str) -> Decimal:
    """Sum amounts that must all match ``currency``; mixed input raises."""
    want = currency.strip().upper()
    if not _CURRENCY_RE.match(want):
        raise MoneyParseError(
            f"currency must be an explicit 3-letter code, got {currency!r}",
            code="invalid_currency",
            raw=None,
        )
    total = Decimal("0")
    for item in items:
        if not isinstance(item, ParsedMoney):
            raise TypeError(f"sum_same_currency expects ParsedMoney, got {type(item).__name__}")
        if item.currency != want:
            raise CurrencyMismatchError(
                f"cannot sum {item.currency} as {want}",
                expected=want,
                found=item.currency,
            )
        total += item.amount
    return total
