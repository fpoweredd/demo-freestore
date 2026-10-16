from django import template

from apps.accounts.formatting import format_balance_amount, format_balance_rub_line

register = template.Library()


@register.filter
def balance_amount(value):
    """Numeric part only, no currency symbol."""
    return format_balance_amount(value)


@register.filter
def balance_rub(value):
    """e.g. '$100', '$123.45' (fractional always two decimals)."""
    return format_balance_rub_line(value)
