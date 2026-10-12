"""FIN-CORE-01 acceptance tests: exact-Decimal parsing + currency-safe totals.

Maps to issue #42 minimum acceptance tests 1-10. Pure unit tests, no services.
"""

from decimal import Decimal

import pytest

from app.finance.money import (
    CurrencyMismatchError,
    MoneyParseError,
    ParsedMoney,
    ParseProfile,
    parse_amount,
    sum_same_currency,
    total_by_currency,
)

EN = ParseProfile(decimal_separator=".", grouping_separator=",")
DE = ParseProfile(decimal_separator=",", grouping_separator=".")
PLAIN = ParseProfile(decimal_separator=".", grouping_separator=None)


# 1. Decimal exactness: 0.1 + 0.2 == 0.3 (no binary-float drift).
def test_exact_decimal_addition_no_float_drift() -> None:
    a = parse_amount("0.1", currency="JOD", profile=PLAIN)
    b = parse_amount("0.2", currency="JOD", profile=PLAIN)
    assert isinstance(a.amount, Decimal) and isinstance(b.amount, Decimal)
    assert a.amount + b.amount == Decimal("0.3")
    assert a.amount + b.amount != Decimal("0.30000000000000004")
    assert 0.1 + 0.2 != 0.3  # documents why float is banned


# 2. Explicit profiles for both separator conventions.
def test_dot_decimal_comma_grouping() -> None:
    assert parse_amount("1,234.567", currency="JOD", profile=EN).amount == Decimal("1234.567")


def test_comma_decimal_dot_grouping() -> None:
    assert parse_amount("1.234,567", currency="JOD", profile=DE).amount == Decimal("1234.567")


def test_grouping_optional_when_profile_allows_it() -> None:
    assert parse_amount("1234.56", currency="JOD", profile=EN).amount == Decimal("1234.56")
    assert parse_amount("1,234.56", currency="JOD", profile=EN).amount == Decimal("1234.56")


def test_space_grouping_profile() -> None:
    sp = ParseProfile(decimal_separator=".", grouping_separator=" ")
    assert parse_amount("1 234.56", currency="JOD", profile=sp).amount == Decimal("1234.56")


# 3. Strict grouping + malformed rejection.
def test_invalid_grouping_positions_rejected() -> None:
    for bad in ("12,34.56", "1,23,456.00", "1,,234.00", ",123.00", "123,.00", "123,"):
        with pytest.raises(MoneyParseError) as exc:
            parse_amount(bad, currency="JOD", profile=EN)
        assert exc.value.code == "invalid_grouping"


def test_identical_separators_rejected_at_profile_construction() -> None:
    with pytest.raises(ValueError):
        ParseProfile(decimal_separator=".", grouping_separator=".")
    with pytest.raises(ValueError):
        ParseProfile(decimal_separator=",", grouping_separator=",")


def test_multiple_decimals_rejected() -> None:
    with pytest.raises(MoneyParseError) as exc:
        parse_amount("1.2.3", currency="JOD", profile=EN)
    assert exc.value.code == "multiple_decimals"
    with pytest.raises(MoneyParseError):
        parse_amount("1,2,3", currency="JOD", profile=DE)


# 4. No inference without an explicit applicable profile.
def test_comma_ambiguous_without_grouping_profile() -> None:
    # "1,234" is 1234 under EN but 1.234 under DE: the caller must decide.
    assert parse_amount("1,234", currency="JOD", profile=EN).amount == Decimal("1234")
    assert parse_amount("1,234", currency="JOD", profile=DE).amount == Decimal("1.234")
    # With no grouping allowed, the comma is rejected rather than guessed.
    with pytest.raises(MoneyParseError):
        parse_amount("1,234", currency="JOD", profile=PLAIN)


def test_missing_profile_is_rejected_not_inferred() -> None:
    with pytest.raises(MoneyParseError) as exc:
        parse_amount("1,234", currency="JOD", profile=None)  # type: ignore[arg-type]
    assert exc.value.code == "invalid_profile"


def test_no_default_currency() -> None:
    with pytest.raises(MoneyParseError) as exc:
        parse_amount("100.00", currency="", profile=EN)
    assert exc.value.code == "invalid_currency"
    with pytest.raises(MoneyParseError):
        parse_amount("100.00", currency="JO", profile=EN)
    with pytest.raises(MoneyParseError):
        parse_amount("100.00", currency="JODD", profile=EN)


# 5. Blank / placeholder / non-finite / wrong-type rejection (never zero).
@pytest.mark.parametrize("raw", ["", "   ", "\t\n "])
def test_blank_rejected(raw: str) -> None:
    with pytest.raises(MoneyParseError) as exc:
        parse_amount(raw, currency="JOD", profile=EN)
    assert exc.value.code == "blank"


@pytest.mark.parametrize("raw", ["N/A", "n/a", "NA", "null", "None", "-", "--", "#N/A", "?"])
def test_placeholders_rejected(raw: str) -> None:
    with pytest.raises(MoneyParseError) as exc:
        parse_amount(raw, currency="JOD", profile=EN)
    assert exc.value.code == "placeholder"


@pytest.mark.parametrize("raw", ["NaN", "nan", "-nan", "inf", "-Inf", "+Infinity", "INFINITY"])
def test_non_finite_rejected(raw: str) -> None:
    with pytest.raises(MoneyParseError) as exc:
        parse_amount(raw, currency="JOD", profile=EN)
    assert exc.value.code == "non_finite"


@pytest.mark.parametrize("raw", ["abc", "12a34", "JOD 100", "100 JOD", "$100", "1_000.00", "10%"])
def test_unsupported_strings_rejected(raw: str) -> None:
    with pytest.raises(MoneyParseError):
        parse_amount(raw, currency="JOD", profile=EN)


@pytest.mark.parametrize("raw", [1.23, 0.1, 123, 0, None, True, b"1.23", Decimal("1.23")])
def test_non_text_types_rejected(raw: object) -> None:
    with pytest.raises(MoneyParseError) as exc:
        parse_amount(raw, currency="JOD", profile=EN)
    assert exc.value.code == "invalid_type"


def test_zero_is_distinct_from_missing() -> None:
    zero = parse_amount("0", currency="JOD", profile=EN)
    assert zero.amount == Decimal("0")
    with pytest.raises(MoneyParseError):
        parse_amount("", currency="JOD", profile=EN)
    with pytest.raises(MoneyParseError):
        parse_amount("N/A", currency="JOD", profile=EN)


# 6. Negatives preserved; no debit/credit interpretation.
def test_negative_preserved() -> None:
    assert parse_amount("-10.250", currency="JOD", profile=EN).amount == Decimal("-10.250")
    assert parse_amount("+10.25", currency="JOD", profile=EN).amount == Decimal("10.25")


@pytest.mark.parametrize("raw", ["(10.25)", "10.25-", "10.25 DR", "10.25 CR", "10.25-"])
def test_accounting_markers_rejected(raw: str) -> None:
    with pytest.raises(MoneyParseError):
        parse_amount(raw, currency="JOD", profile=EN)


# 7. Raw retained independently; no float intermediates.
def test_raw_preserved_and_decimal_exact() -> None:
    pm = parse_amount("  1,234.50  ", currency="JOD", profile=EN)
    assert pm.raw == "  1,234.50  "
    assert isinstance(pm.amount, Decimal) and not isinstance(pm.amount, float)
    assert pm.amount == Decimal("1234.50")
    assert str(pm.amount) == "1234.50"  # trailing zero kept in representation


def test_currency_normalized_but_retained() -> None:
    pm = parse_amount("100.00", currency="jod", profile=EN)
    assert pm.currency == "JOD"
    assert isinstance(pm, ParsedMoney)


# 8. Currency-segregated aggregation; mixed addition forbidden.
def test_totals_segregated_by_currency() -> None:
    items = [
        parse_amount("100.00", currency="JOD", profile=EN),
        parse_amount("50.25", currency="JOD", profile=EN),
        parse_amount("10.00", currency="USD", profile=EN),
    ]
    assert total_by_currency(items) == {"JOD": Decimal("150.25"), "USD": Decimal("10.00")}


def test_empty_totals_is_empty_dict_not_zero() -> None:
    assert total_by_currency([]) == {}


def test_direct_mixed_addition_raises() -> None:
    jod = parse_amount("1.00", currency="JOD", profile=EN)
    usd = parse_amount("1.00", currency="USD", profile=EN)
    with pytest.raises(CurrencyMismatchError):
        _ = jod + usd
    assert (jod + parse_amount("2.00", currency="JOD", profile=EN)).amount == Decimal("3.00")


def test_sum_same_currency_rejects_mixed() -> None:
    items = [
        parse_amount("1.00", currency="JOD", profile=EN),
        parse_amount("1.00", currency="USD", profile=EN),
    ]
    with pytest.raises(CurrencyMismatchError):
        sum_same_currency(items, currency="JOD")
    assert sum_same_currency(items[:1], currency="JOD") == Decimal("1.00")


def test_totals_are_decimal_and_pure() -> None:
    items = [parse_amount("0.1", currency="JOD", profile=PLAIN)]
    out = total_by_currency(items)
    assert isinstance(out["JOD"], Decimal)
    out["JOD"] = Decimal("999")
    assert total_by_currency(items) == {"JOD": Decimal("0.1")}


# 9. Precision preserved; no silent JOD 3-dp rounding.
def test_sub_fils_precision_preserved() -> None:
    pm = parse_amount("0.0001", currency="JOD", profile=EN)
    assert pm.amount == Decimal("0.0001")
    assert str(pm.amount) == "0.0001"
    assert pm.amount.as_tuple().exponent == -4


def test_trailing_zeros_and_long_fractions_preserved() -> None:
    assert str(parse_amount("10.250", currency="JOD", profile=EN).amount) == "10.250"
    assert parse_amount("1,234.5678", currency="JOD", profile=EN).amount == Decimal("1234.5678")
    assert parse_amount("-0.0001", currency="JOD", profile=EN).amount == Decimal("-0.0001")


# 10. Error behavior fully typed; fail-closed on abuse.
def test_error_carries_code_and_raw() -> None:
    with pytest.raises(MoneyParseError) as exc:
        parse_amount("12,34.56", currency="JOD", profile=EN)
    assert exc.value.code == "invalid_grouping"
    assert exc.value.raw == "12,34.56"
    assert isinstance(exc.value, ValueError)


def test_oversize_input_rejected() -> None:
    with pytest.raises(MoneyParseError) as exc:
        parse_amount("9" * 65, currency="JOD", profile=EN)
    assert exc.value.code == "too_long"


def test_non_ascii_digits_rejected() -> None:
    with pytest.raises(MoneyParseError):
        parse_amount("١٢٣.٤٥", currency="JOD", profile=EN)  # Arabic-Indic digits


def test_totals_reject_non_parsed_items() -> None:
    with pytest.raises(TypeError):
        total_by_currency(["1.00"])  # type: ignore[list-item]
