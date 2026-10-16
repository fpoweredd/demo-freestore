"""Human-readable balance strings for UI."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def format_balance_amount(value) -> str:
    """
    Whole dollars -> integer string only (100, not 100.00).
    Fractional -> always two digits after the decimal (10.50 not 10.5).
    """
    if value is None:
        return "0"
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "0"
    quantized = d.quantize(Decimal("0.01"))
    if quantized == quantized.to_integral():
        return str(int(quantized))
    return format(quantized, ".2f")


def format_balance_rub_line(value) -> str:
    """Legacy name kept for templates/context; displays USD ($)."""
    return f"${format_balance_amount(value)}"
