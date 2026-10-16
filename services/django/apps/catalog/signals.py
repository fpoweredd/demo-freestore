from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from loguru import logger

from .models import DigitalItem


@receiver(post_save, sender=DigitalItem)
def auto_fulfill_preorders_on_digital_item_create(sender, instance: DigitalItem, created: bool, **kwargs) -> None:
    # Trigger not only on create, but also when an item becomes available again.
    if instance.is_used or instance.reserved_at is not None:
        return

    def _run() -> None:
        try:
            from apps.orders.services import (
                fulfill_waiting_stock_orders_for_product,
                reconcile_waiting_stock_orders,
            )

            fulfill_waiting_stock_orders_for_product(product=instance.product)
            reconcile_waiting_stock_orders()
        except Exception:
            logger.exception("auto_fulfill_preorders_failed product_id={}", instance.product_id)

    transaction.on_commit(_run)
