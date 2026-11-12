"""Money and weight rules of stapel-delivery: Decimal inside, strings on the wire.

A shipping price is computed from a rate (``services/rates.py``) and is
bounded by the rate columns: ``amount < 10^10``. The weight part
(``per_kg × weight``) is unbounded in principle, so a computed price at or
above :data:`AMOUNT_LIMIT` is "not offered" rather than a wider column —
``tests/test_money_bounds.py`` derives the bound from these constants and
the field declarations.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

#: Decimal places of every money column (currencies with exponent 2 only).
DECIMAL_PLACES = 2
QUANTUM = Decimal("0.01")

#: Rate column width (max_digits) — models.py reads this, never a literal.
AMOUNT_MAX_DIGITS = 12
AMOUNT_INTEGER_DIGITS = AMOUNT_MAX_DIGITS - DECIMAL_PLACES

#: Strict upper bound of any price this module stores or answers.
AMOUNT_LIMIT = Decimal(10) ** AMOUNT_INTEGER_DIGITS

#: Weight columns: kilograms with gram precision.
WEIGHT_DECIMAL_PLACES = 3
WEIGHT_QUANTUM = Decimal("0.001")
WEIGHT_MAX_DIGITS = 12
#: Strict upper bound of a stored weight.
WEIGHT_LIMIT = Decimal(10) ** (WEIGHT_MAX_DIGITS - WEIGHT_DECIMAL_PLACES)


class MalformedAmount(ValueError):
    """A money or weight value that is not a non-negative finite decimal."""


def parse_decimal(raw, *, field: str = "value") -> Decimal:
    """A wire decimal (string or int) as a Decimal; floats are refused."""
    if isinstance(raw, (float, bool)) or raw is None:
        raise MalformedAmount(f"{field} must be a decimal string, got {raw!r}")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        raise MalformedAmount(f"{field} is not a decimal: {raw!r}") from None
    if not value.is_finite() or value < 0:
        raise MalformedAmount(f"{field} must be finite and non-negative: {raw!r}")
    return value


def parse_grams(raw) -> Decimal | None:
    """``attrs.weight_grams`` (integer grams) as kilograms; ``None`` when absent or unreadable.

    It is a catalog attribute, not money: an integral number or a digit
    string is accepted; anything else (a fraction, a negative, a bool) is
    "unknown", which prices flat.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, float):
        if not raw.is_integer():
            return None
        raw = int(raw)
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw.isdigit():
            return None
        raw = int(raw)
    if not isinstance(raw, int) or raw < 0:
        return None
    return Decimal(raw) / Decimal(1000)


def quantize(value: Decimal) -> Decimal:
    return value.quantize(QUANTUM, rounding=ROUND_HALF_UP)


def quantize_weight(value: Decimal) -> Decimal:
    return value.quantize(WEIGHT_QUANTUM, rounding=ROUND_HALF_UP)


def to_wire(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(QUANTUM))
