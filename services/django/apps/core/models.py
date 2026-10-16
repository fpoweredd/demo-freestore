from __future__ import annotations

from django.db import models


class ShopSettings(models.Model):
    """
    Global operational switches for storefront behavior.
    Keep exactly one row (singleton via save override).
    """

    maintenance_mode = models.BooleanField(
        default=False,
        help_text="If enabled, storefront is in maintenance mode.",
    )
    buy_enabled = models.BooleanField(
        default=True,
        help_text="If disabled, new checkout/order creation is blocked.",
    )
    refill_enabled = models.BooleanField(
        default=True,
        help_text="If disabled, balance top-up is blocked.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Shop settings"
        verbose_name_plural = "Shop settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return "Shop settings"
