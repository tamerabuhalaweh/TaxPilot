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


# FIN-43-R1: aggregation must be exact independent of ambient Decimal precision.
# Bare Decimal `+` observes getcontext().prec (default 28) and silently rounds
# valid long inputs; the regression below failed before the integer-scaled fix.
def test_review_repro_cent_preserved_for_28_digit_whole() -> None:
    import decimal

    big = parse_amount("1000000000000000000000000000.00", currency="JOD", profile=EN)
    cent = parse_amount("0.01", currency="JOD", profile=EN)
    expected = Decimal("1000000000000000000000000000.01")
    with decimal.localcontext() as ctx:
        ctx.prec = 28
        assert big.amount + cent.amount != expected  # documents the default-context trap
    assert total_by_currency([big, cent]) == {"JOD": expected}
    assert sum_same_currency([big, cent], currency="JOD") == expected
    assert (big + cent).amount == expected


def test_exact_long_sums_under_low_ambient_precision() -> None:
    import decimal

    pos = parse_amount("12345678901234567890123456789.12345", currency="JOD", profile=PLAIN)
    tiny = parse_amount("0.00001", currency="JOD", profile=PLAIN)
    neg = parse_amount("-9999999999999999999999999999.99", currency="JOD", profile=PLAIN)
    neg_cent = parse_amount("-0.01", currency="JOD", profile=PLAIN)
    with decimal.localcontext() as ctx:
        ctx.prec = 10  # hostile ambient precision; helpers must stay exact anyway
        assert sum_same_currency([pos, tiny], currency="JOD") == Decimal(
            "12345678901234567890123456789.12346"
        )
        assert sum_same_currency([neg, neg_cent], currency="JOD") == Decimal(
            "-10000000000000000000000000000.00"
        )
        assert (pos + tiny).amount == Decimal("12345678901234567890123456789.12346")
        assert (neg + neg_cent).amount == Decimal("-10000000000000000000000000000.00")


def test_exact_grouped_34_digit_parse_and_mixed_currency_totals() -> None:
    import decimal

    grouped = parse_amount("12,345,678,901,234,567,890,123,456,789.12345", currency="JOD", profile=EN)
    assert grouped.amount == Decimal("12345678901234567890123456789.12345")
    usd_big = parse_amount("98765432109876543210987654321.99", currency="USD", profile=PLAIN)
    usd_cent = parse_amount("0.01", currency="USD", profile=PLAIN)
    with decimal.localcontext() as ctx:
        ctx.prec = 10
        totals = total_by_currency([grouped, usd_big, usd_cent])
    assert totals == {
        "JOD": Decimal("12345678901234567890123456789.12345"),
        "USD": Decimal("98765432109876543210987654322.00"),
    }


def test_exact_bulk_total_of_long_values() -> None:
    import decimal

    row = parse_amount("12345678901234567890.12", currency="JOD", profile=PLAIN)
    with decimal.localcontext() as ctx:
        ctx.prec = 10
        assert sum_same_currency([row] * 100, currency="JOD") == Decimal("1234567890123456789012.00")


# FIN-43-R2: ParsedMoney enforces invariants at construction, not just via the parser.
def test_direct_construction_float_amount_rejected() -> None:
    with pytest.raises(MoneyParseError) as exc:
        ParsedMoney(raw="0.1", amount=0.1, currency="JOD")  # type: ignore[arg-type]
    assert exc.value.code == "invalid_type"


@pytest.mark.parametrize("raw", [100, 0, None, True, b"1.00", "1.00"])
def test_direct_construction_non_decimal_amount_rejected(raw: object) -> None:
    with pytest.raises(MoneyParseError) as exc:
        ParsedMoney(raw="1.00", amount=raw, currency="JOD")  # type: ignore[arg-type]
    assert exc.value.code == "invalid_type"


@pytest.mark.parametrize("raw", [Decimal("NaN"), Decimal("-NaN"), Decimal("Infinity")])
def test_direct_construction_non_finite_rejected(raw: Decimal) -> None:
    with pytest.raises(MoneyParseError) as exc:
        ParsedMoney(raw="bad", amount=raw, currency="JOD")
    assert exc.value.code == "non_finite"


@pytest.mark.parametrize("raw", ["", "   ", "JO", "JODD", "J0D", "12", None, 123])
def test_direct_construction_invalid_currency_rejected(raw: object) -> None:
    with pytest.raises(MoneyParseError) as exc:
        ParsedMoney(raw="1.00", amount=Decimal("1.00"), currency=raw)  # type: ignore[arg-type]
    assert exc.value.code == "invalid_currency"


@pytest.mark.parametrize("raw", [123, None, 1.5, b"1.00"])
def test_direct_construction_non_text_raw_rejected(raw: object) -> None:
    with pytest.raises(MoneyParseError) as exc:
        ParsedMoney(raw=raw, amount=Decimal("1.00"), currency="JOD")  # type: ignore[arg-type]
    assert exc.value.code == "invalid_type"


def test_direct_construction_blank_raw_rejected() -> None:
    with pytest.raises(MoneyParseError) as exc:
        ParsedMoney(raw="   ", amount=Decimal("1.00"), currency="JOD")
    assert exc.value.code == "blank"


def test_direct_construction_valid_canonicalizes_currency() -> None:
    pm = ParsedMoney(raw="src cell A1", amount=Decimal("1.00"), currency="jod")
    assert pm.currency == "JOD" and pm.is_derived is False


# FIN-43-R3: public package entry point + derived-raw provenance marker.
def test_package_entry_point_import() -> None:
    import app.finance as pkg
    from app.finance import parse_amount as via_package

    assert "parse_amount" in pkg.__all__
    pm = via_package("1,234.56", currency="JOD", profile=EN)
    assert pm.amount == Decimal("1234.56") and pm.is_derived is False


def test_derived_raw_marked_not_source_evidence() -> None:
    a = parse_amount("10.00", currency="JOD", profile=EN)
    b = parse_amount("0.01", currency="JOD", profile=EN)
    derived = a + b
    assert derived.is_derived is True
    assert derived.amount == Decimal("10.01")
    assert derived.raw != a.raw and derived.raw != b.raw  # expression, not source
    assert a.is_derived is False and b.is_derived is False  # sources stay unmarked
