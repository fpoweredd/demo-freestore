"""Which providers are exposed in UI (DB + API keys + per-screen rules)."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings

from apps.core.ui_text import PROVIDER_UI_LABELS

from . import PAYMENT_PROVIDERS, STUB_PROVIDER_IDS


def is_stub_provider(provider_id: str) -> bool:
    return (provider_id or "").strip().lower() in STUB_PROVIDER_IDS


def provider_is_configured(provider_id: str) -> bool:
    key = (provider_id or "").strip().lower()
    if is_stub_provider(key):
        # Stub buttons are always "configured"; real keys come later.
        return True
    if key == "nowpayments":
        return bool((getattr(settings, "NOWPAYMENTS_API_KEY_SECRET", "") or "").strip())
    if key == "rollypay":
        api = (getattr(settings, "ROLLYPAY_API_KEY", "") or "").strip()
        sec = (getattr(settings, "ROLLYPAY_SIGNING_SECRET", "") or "").strip()
        return bool(api and sec)
    if key == "enot":
        shop = (getattr(settings, "ENOT_SHOP_ID", "") or "").strip()
        api = (getattr(settings, "ENOT_API_KEY", "") or "").strip()
        hook = (getattr(settings, "ENOT_WEBHOOK_SECRET", "") or "").strip()
        return bool(shop and api and hook)
    return False


def get_enabled_provider_ids() -> list[str]:
    """Providers enabled in admin and configured with credentials, sorted for UI."""
    from apps.payments.models import PaymentProviderSettings

    rows = PaymentProviderSettings.objects.filter(is_enabled=True).values_list(
        "provider_id", "ui_sort_order"
    )
    ordered: list[tuple[int, str]] = []
    for pid, sort_order in rows:
        key = (pid or "").strip().lower()
        if key not in PAYMENT_PROVIDERS:
            continue
        if not provider_is_configured(key):
            continue
        ordered.append((int(sort_order or 0), key))
    out: list[str] = []
    for _, key in sorted(ordered, key=lambda x: (x[0], x[1])):
        if key not in out:
            out.append(key)
    return out


def get_provider_topup_limits(provider_id: str) -> tuple[Decimal, Decimal]:
    """Min/max top-up (RUB) from admin. Raises PaymentProviderSettings.DoesNotExist if row missing."""
    from apps.payments.models import PaymentProviderSettings

    row = PaymentProviderSettings.objects.get(
        provider_id=(provider_id or "").strip().lower()
    )
    return row.balance_topup_min_amount, row.balance_topup_max_amount


def get_topup_provider_buttons() -> list[dict]:
    """Buttons for balance top-up page (enabled + configured), sorted by ui_sort_order."""
    from apps.payments.models import PaymentProviderSettings

    rows = (
        PaymentProviderSettings.objects.filter(is_enabled=True)
        .order_by("ui_sort_order", "provider_id")
        .values(
            "provider_id",
            "ui_sort_order",
            "balance_topup_min_amount",
            "balance_topup_max_amount",
        )
    )
    out: list[dict] = []
    for row in rows:
        key = (row["provider_id"] or "").strip().lower()
        if key not in PAYMENT_PROVIDERS:
            continue
        if not provider_is_configured(key):
            continue
        # Stubs are for product checkout UI only — hide on top-up.
        if is_stub_provider(key):
            continue
        out.append(
            {
                "id": key,
                "label": PROVIDER_UI_LABELS.get(key, key),
                "sort_order": int(row["ui_sort_order"] or 0),
                "min_amount": str(row["balance_topup_min_amount"]),
                "max_amount": str(row["balance_topup_max_amount"]),
            }
        )
    return out


def get_product_provider_buttons() -> list[dict]:
    """Provider button configs for product page (without internal balance rail)."""
    from apps.payments.models import PaymentProviderSettings

    rows = (
        PaymentProviderSettings.objects.filter(is_enabled=True, show_on_product_page=True)
        .order_by("ui_sort_order", "provider_id")
        .values("provider_id", "ui_sort_order", "product_min_amount")
    )
    out: list[dict] = []
    for row in rows:
        key = (row["provider_id"] or "").strip().lower()
        if key not in PAYMENT_PROVIDERS:
            continue
        if not provider_is_configured(key):
            continue
        out.append(
            {
                "id": key,
                "label": PROVIDER_UI_LABELS.get(key, key),
                "sort_order": int(row["ui_sort_order"] or 0),
                "min_product_amount": str(row["product_min_amount"]),
                "is_stub": is_stub_provider(key),
            }
        )
    return out
