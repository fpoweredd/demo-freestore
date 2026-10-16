from decimal import Decimal

from django.conf import settings

from apps.accounts.formatting import format_balance_rub_line


def turnstile(request):
    return {
        "turnstile_site_key": getattr(settings, "TURNSTILE_SITE_KEY", "") or "",
    }


def account_balance_header(request):
    """Header badge: current profile balance (one lightweight query when authenticated)."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"header_balance_rub": format_balance_rub_line(Decimal("0"))}

    from apps.accounts.models import AccountProfile

    bal = AccountProfile.objects.filter(user_id=request.user.pk).values_list(
        "balance", flat=True
    ).first()
    if bal is None:
        bal = Decimal("0")
    return {"header_balance_rub": format_balance_rub_line(bal)}

