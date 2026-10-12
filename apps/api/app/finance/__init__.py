"""Financial core primitives (pure, side-effect-free).

Only re-exports the stable FIN-CORE-01 surface. No API/DB/worker imports.
"""

from app.finance.money import (
    CurrencyMismatchError,
    MoneyParseError,
    ParsedMoney,
    ParseProfile,
    parse_amount,
    sum_same_currency,
    total_by_currency,
)

__all__ = [
    "CurrencyMismatchError",
    "MoneyParseError",
    "ParsedMoney",
    "ParseProfile",
    "parse_amount",
    "sum_same_currency",
    "total_by_currency",
]
