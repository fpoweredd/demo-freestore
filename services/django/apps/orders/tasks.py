from __future__ import annotations

from django.conf import settings
from celery import shared_task
from loguru import logger

from apps.payments.services import poll_awaiting_order_payments

from .services import (
    cancel_stale_unpaid_orders,
    complete_stale_manual_pending_orders,
    reconcile_waiting_stock_orders,
    retry_due_order_telegram_notifications,
)


@shared_task
def reconcile_waiting_stock_orders_task() -> int:
    completed = int(reconcile_waiting_stock_orders())
    logger.info("reconcile_waiting_stock_orders_task completed_orders={}", completed)
    return completed


@shared_task
def cancel_stale_unpaid_orders_task() -> int:
    cancelled = int(
        cancel_stale_unpaid_orders(
            order_ttl_hours=int(getattr(settings, "ORDER_AUTO_CANCEL_HOURS", 24) or 24),
            reservation_ttl_minutes=int(
                getattr(settings, "RESERVATION_TTL_MINUTES", 30) or 30
            ),
        )
    )
    logger.info("cancel_stale_unpaid_orders_task cancelled_orders={}", cancelled)
    return cancelled


@shared_task
def complete_stale_manual_pending_orders_task() -> int:
    completed = int(
        complete_stale_manual_pending_orders(
            ttl_hours=int(
                getattr(settings, "MANUAL_PENDING_AUTO_COMPLETE_HOURS", 48) or 48
            ),
        )
    )
    logger.info(
        "complete_stale_manual_pending_orders_task completed_orders={}", completed
    )
    return completed


@shared_task
def poll_awaiting_order_payments_task() -> int:
    reconciled = int(
        poll_awaiting_order_payments(
            batch_limit=int(getattr(settings, "PAYMENT_POLL_BATCH_LIMIT", 200) or 200)
        )
    )
    logger.info("poll_awaiting_order_payments_task reconciled_orders={}", reconciled)
    return reconciled


@shared_task
def retry_due_order_telegram_notifications_task() -> int:
    processed, succeeded = retry_due_order_telegram_notifications(
        batch_limit=int(
            getattr(settings, "TELEGRAM_NOTIFY_RETRY_BATCH_LIMIT", 200) or 200
        )
    )
    logger.info(
        "retry_due_order_telegram_notifications_task processed={} succeeded={} failed={}",
        processed,
        succeeded,
        max(processed - succeeded, 0),
    )
    return processed
