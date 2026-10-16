from __future__ import annotations

from .models import ShopSettings


def get_shop_settings() -> ShopSettings:
    obj, _ = ShopSettings.objects.get_or_create(
        pk=1,
        defaults={
            "maintenance_mode": False,
            "buy_enabled": True,
            "refill_enabled": True,
        },
    )
    return obj
