from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from loguru import logger

from apps.accounts.models import AccountProfile
from apps.core.bot_api_client import post_payment_error_notify, post_topup_notify
from apps.core.services import get_shop_settings
from apps.orders.models import Order
from apps.orders.services import process_paid_order

from .internal_balance import INTERNAL_BALANCE_PROVIDER_ID
from .models import (
    BalanceTopUp,
    Payment,
    PaymentRefund,
    PaymentWebhookLog,
    WalletTransaction,
)
from .providers import get_provider


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def _wallet_description(
    *,
    kind: str,
    amount: Decimal,
    order: Order | None = None,
    topup: BalanceTopUp | None = None,
) -> str:
    if kind == WalletTransaction.Kind.TOPUP_CREDIT and topup:
        return f"Balance top-up {topup.public_id}"
    if kind == WalletTransaction.Kind.ORDER_DEBIT and order:
        return f"Order payment {order.public_id}"
    if kind == WalletTransaction.Kind.REFUND_CREDIT and order:
        return f"Refund for order {order.public_id}"
    if kind == WalletTransaction.Kind.CHARGEBACK_DEBIT and topup:
        return f"Refund reversal for top-up {topup.public_id}"
    sign = "+" if amount > 0 else ""
    return f"Wallet operation {sign}{amount}"


@transaction.atomic
def create_wallet_transaction(
    *,
    user_id: int,
    kind: str,
    source_type: str,
    source_id: str,
    amount: Decimal,
    currency: str,
    description: str = "",
    metadata: dict[str, Any] | None = None,
) -> WalletTransaction | None:
    profile = AccountProfile.objects.select_for_update().get(user_id=user_id)
    current_balance = profile.balance or Decimal("0")
    new_balance = current_balance + amount

    try:
        tx = WalletTransaction.objects.create(
            user_id=user_id,
            kind=kind,
            source_type=source_type,
            source_id=source_id,
            amount=amount,
            currency=currency,
            balance_before=current_balance,
            balance_after=new_balance,
            description=description,
            metadata=metadata or {},
        )
    except IntegrityError:
        return None

    profile.balance = new_balance
    profile.save(update_fields=["balance", "updated_at"])
    return tx


def assert_can_init_payment(*, order: Order, user, guest_email: str | None) -> None:
    from rest_framework.exceptions import PermissionDenied, ValidationError

    if order.status != Order.Status.AWAITING_PAYMENT:
        raise ValidationError({"order_public_id": "Order is not awaiting payment."})

    if user and user.is_authenticated:
        if order.user_id and order.user_id != user.pk:
            raise PermissionDenied()
        return

    if order.user_id:
        raise PermissionDenied("Authentication required for this order.")
    ge = _normalize_email(order.guest_email or "")
    if not ge or ge != _normalize_email(guest_email or ""):
        raise PermissionDenied("Guest email does not match the order.")


def find_payment_for_provider_ipn(payload: dict, provider_key: str) -> Payment | None:
    prov = (provider_key or "").strip().lower()
    pid = payload.get("payment_id") or payload.get("id") or payload.get("invoice_id")
    if pid is not None:
        found = (
            Payment.objects.filter(provider_payment_id=str(pid))
            .select_related("order", "balance_top_up")
            .first()
        )
        if found:
            return found

    oid = payload.get("order_id")
    if oid is None:
        return None
    try:
        pub = int(oid)
    except (TypeError, ValueError):
        return None

    order = Order.objects.filter(public_id=pub).first()
    if order:
        return (
            Payment.objects.filter(order=order, provider=prov)
            .order_by("-created_at")
            .first()
        )

    topup = BalanceTopUp.objects.filter(public_id=pub).first()
    if topup:
        return (
            Payment.objects.filter(balance_top_up=topup, provider=prov)
            .order_by("-created_at")
            .first()
        )

    return None


def find_payment_for_nowpayments_payload(payload: dict) -> Payment | None:
    return find_payment_for_provider_ipn(payload, "nowpayments")


def _map_np_status_to_payment(provider_status: str, is_success: bool) -> str:
    s = (provider_status or "").lower()
    if is_success:
        return Payment.Status.SUCCEEDED
    if s in ("failed",):
        return Payment.Status.FAILED
    if s in ("expired",):
        return Payment.Status.EXPIRED
    if s in ("refunded",):
        return Payment.Status.REFUNDED
    return Payment.Status.PROCESSING


def _map_rollypay_status_to_payment(provider_status: str, is_success: bool) -> str:
    s = (provider_status or "").lower()
    if is_success:
        return Payment.Status.SUCCEEDED
    if s in ("refunded", "chargeback"):
        return Payment.Status.REFUNDED
    if s in ("expired",):
        return Payment.Status.EXPIRED
    if s in ("canceled", "failed"):
        return Payment.Status.FAILED
    return Payment.Status.PROCESSING


def _map_enot_status_to_payment(provider_status: str, is_success: bool) -> str:
    s = (provider_status or "").lower()
    if is_success:
        return Payment.Status.SUCCEEDED
    if s in ("refund",):
        return Payment.Status.REFUNDED
    if s in ("expired",):
        return Payment.Status.EXPIRED
    if s in ("fail", "failed"):
        return Payment.Status.FAILED
    if s in ("created",):
        return Payment.Status.PROCESSING
    return Payment.Status.PROCESSING


def _map_provider_status_to_payment(
    provider_key: str, provider_status: str, is_success: bool
) -> str:
    key = (provider_key or "").strip().lower()
    if key == "rollypay":
        return _map_rollypay_status_to_payment(provider_status, is_success)
    if key == "enot":
        return _map_enot_status_to_payment(provider_status, is_success)
    return _map_np_status_to_payment(provider_status, is_success)


def _format_money(value: Decimal) -> str:
    return str(Decimal(value).quantize(Decimal("0.01")))


def _topup_user_public_id(user_id: int) -> str:
    profile = AccountProfile.objects.filter(user_id=user_id).only("public_id").first()
    if not profile:
        return "-"
    return str(profile.public_id or "-")


def _notify_topup_event(
    *,
    payment: Payment,
    topup: BalanceTopUp,
    success: bool,
    status_text: str,
    reason: str = "",
) -> None:
    dedup_key = f"tg_topup_notify:{payment.pk}:{status_text}:{int(success)}"
    if not cache.add(dedup_key, 1, timeout=30 * 24 * 3600):
        return
    payload = {
        "topup_public_id": int(topup.public_id),
        "payment_id": str(payment.pk),
        "provider_id": str(payment.provider or "").strip() or "-",
        "amount_rub": _format_money(Decimal(topup.amount)),
        "currency": str(topup.currency or "USD"),
        "status": status_text,
        "success": bool(success),
        "reason": (reason or "").strip(),
        "user_public_id": _topup_user_public_id(topup.user_id),
        "user_email": str(getattr(topup.user, "email", "") or "").strip() or "-",
    }
    post_topup_notify(payload)


def _notify_provider_payment_failed(
    *,
    payment: Payment,
    provider_status: str,
) -> None:
    """Telegram alert for terminal provider failure (fail), not expiry."""
    ctx: dict[str, str] = {
        "payment_id": str(payment.pk),
        "provider_status": (provider_status or "").strip() or "-",
    }
    if payment.order_id and payment.order:
        ctx["order_public_id"] = str(payment.order.public_id)
    if payment.balance_top_up_id and payment.balance_top_up:
        ctx["topup_public_id"] = str(payment.balance_top_up.public_id)
    _notify_payment_error(
        provider_id=payment.provider,
        error_code="payment_failed",
        error_message="Provider reported payment failure (not expired).",
        context=ctx,
    )


def _notify_payment_error(
    *,
    provider_id: str,
    error_code: str,
    error_message: str,
    context: dict[str, str] | None = None,
) -> None:
    dedup_key = (
        "tg_payment_error:"
        f"{provider_id}:{error_code}:{error_message}:{json.dumps(context or {}, sort_keys=True)}"
    )
    if not cache.add(dedup_key, 1, timeout=3600):
        return
    payload = {
        "provider_id": (provider_id or "").strip() or "-",
        "error_code": (error_code or "").strip() or "unknown_error",
        "error_message": (error_message or "").strip() or "Unknown payment error",
        "context": {k: str(v) for k, v in (context or {}).items()},
    }
    post_payment_error_notify(payload)


@transaction.atomic
def pay_order_with_wallet(*, order: Order, user) -> Payment:
    from rest_framework.exceptions import PermissionDenied, ValidationError

    if not user or not user.is_authenticated:
        raise PermissionDenied("Authentication required for wallet payments.")

    profile = AccountProfile.objects.select_for_update().get(user_id=user.pk)
    if (profile.balance or Decimal("0")) < order.total:
        raise ValidationError({"provider": "Insufficient wallet balance."})

    existing = (
        Payment.objects.select_for_update()
        .filter(
            order=order,
            provider=INTERNAL_BALANCE_PROVIDER_ID,
            status=Payment.Status.SUCCEEDED,
        )
        .order_by("-created_at")
        .first()
    )
    if existing:
        return existing

    payment = Payment.objects.create(
        order=order,
        balance_top_up=None,
        provider=INTERNAL_BALANCE_PROVIDER_ID,
        amount=order.total,
        currency=order.currency,
        status=Payment.Status.PENDING,
        provider_status="wallet_pending",
        idempotency_key=f"wallet-ord-{order.public_id}"[:64],
    )

    tx = create_wallet_transaction(
        user_id=user.pk,
        kind=WalletTransaction.Kind.ORDER_DEBIT,
        source_type=WalletTransaction.SourceType.PAYMENT,
        source_id=str(payment.pk),
        amount=-Decimal(order.total),
        currency=order.currency,
        description=_wallet_description(
            kind=WalletTransaction.Kind.ORDER_DEBIT,
            amount=-Decimal(order.total),
            order=order,
        ),
        metadata={
            "payment_id": str(payment.pk),
            "order_id": order.pk,
            "order_public_id": order.public_id,
        },
    )
    if tx is None:
        payment.refresh_from_db()
        return payment

    payment.status = Payment.Status.SUCCEEDED
    payment.provider_status = "wallet_succeeded"
    payment.save(update_fields=["status", "provider_status", "updated_at"])

    if order.status == Order.Status.AWAITING_PAYMENT:
        process_paid_order(order)

    return payment


def init_payment_for_order(
    *,
    order_public_id: int,
    provider_name: str,
    user,
    guest_email: str | None,
) -> Payment:
    order = Order.objects.filter(public_id=order_public_id).first()
    if not order:
        from rest_framework.exceptions import NotFound

        raise NotFound()

    assert_can_init_payment(order=order, user=user, guest_email=guest_email)

    provider_key = provider_name.strip().lower()
    if provider_key == INTERNAL_BALANCE_PROVIDER_ID:
        return pay_order_with_wallet(order=order, user=user)

    existing = (
        Payment.objects.filter(
            order=order,
            provider=provider_key,
            status__in=[Payment.Status.PENDING, Payment.Status.PROCESSING],
        )
        .order_by("-created_at")
        .first()
    )
    if existing and existing.invoice_url:
        return existing

    prov = get_provider(provider_key)
    idem_key = f"ord-{order.public_id}-{provider_key}"
    from django.conf import settings

    site = str(getattr(settings, "PUBLIC_SITE_URL", "http://127.0.0.1:8000")).rstrip(
        "/"
    )
    order_rel_url = f"/orders/{order.public_id}/"
    order_return_url = f"{site}{order_rel_url}"
    payment = Payment.objects.create(
        order=order,
        balance_top_up=None,
        provider=provider_key,
        amount=order.total,
        currency=order.currency,
        status=Payment.Status.PENDING,
        idempotency_key=idem_key[:64],
    )

    try:
        result = prov.create_invoice(
            reference_id=order.public_id,
            amount=Decimal(order.total),
            currency=order.currency,
            idempotency_key=idem_key,
            order_description=f"Order {order.public_id}",
            success_url=order_return_url,
            cancel_url=order_return_url,
        )
    except RuntimeError:
        payment.status = Payment.Status.FAILED
        payment.provider_status = "invoice_error"
        payment.save(update_fields=["status", "provider_status", "updated_at"])
        transaction.on_commit(
            lambda order=order, provider_key=provider_key: _notify_payment_error(
                provider_id=provider_key,
                error_code="invoice_error_order",
                error_message="Failed to create payment invoice for order checkout.",
                context={
                    "order_public_id": str(order.public_id),
                    "payment_id": str(payment.pk),
                },
            )
        )
        raise

    payment.invoice_url = result.get("invoice_url") or ""
    ext_id = result.get("provider_payment_id")
    if ext_id:
        collision = (
            Payment.objects.filter(provider_payment_id=str(ext_id))
            .exclude(pk=payment.pk)
            .exists()
        )
        if not collision:
            payment.provider_payment_id = str(ext_id)
    payment.status = Payment.Status.PROCESSING
    payment.save(
        update_fields=["invoice_url", "provider_payment_id", "status", "updated_at"]
    )
    return payment


def _balance_topup_urls() -> tuple[str, str]:
    from django.conf import settings

    site = str(getattr(settings, "PUBLIC_SITE_URL", "http://127.0.0.1:8000")).rstrip(
        "/"
    )
    ok_rel = str(
        getattr(
            settings,
            "BALANCE_TOPUP_SUCCESS_REL_PATH",
            "/accounts/balance/topup-result/?topup=success",
        )
    )
    cancel_rel = str(
        getattr(
            settings,
            "BALANCE_TOPUP_CANCEL_REL_PATH",
            "/accounts/balance/topup-result/?topup=cancel",
        )
    )
    if not ok_rel.startswith("/"):
        ok_rel = "/" + ok_rel.lstrip("/")
    if not cancel_rel.startswith("/"):
        cancel_rel = "/" + cancel_rel.lstrip("/")
    return f"{site}{ok_rel}", f"{site}{cancel_rel}"


def _validate_topup_amount(amount: Decimal, provider_name: str) -> None:
    from rest_framework.exceptions import ValidationError

    from apps.payments.models import PaymentProviderSettings

    from .providers.registry import get_provider_topup_limits

    key = provider_name.strip().lower()
    try:
        min_a, max_a = get_provider_topup_limits(key)
    except PaymentProviderSettings.DoesNotExist:
        raise ValidationError(
            {"provider": "This payment method is not configured in admin."}
        ) from None

    if amount < min_a:
        raise ValidationError({"amount": f"Minimum top-up is {min_a} USD."})
    if amount > max_a:
        raise ValidationError({"amount": f"Maximum top-up is {max_a} USD."})

    prov = get_provider(provider_name)
    if amount < prov.min_amount:
        raise ValidationError({"amount": f"Provider API minimum is {prov.min_amount}."})


def init_balance_topup_payment(
    *, user, amount: Decimal, currency: str, provider_name: str
) -> Payment:
    """Logged-in user only. Creates BalanceTopUp + Payment and returns invoice redirect target."""
    from rest_framework.exceptions import PermissionDenied, ValidationError

    from .providers.registry import get_enabled_provider_ids

    if not user or not user.is_authenticated:
        raise PermissionDenied()
    if not get_shop_settings().refill_enabled:
        raise ValidationError({"provider": "Balance top-up is temporarily disabled."})

    key = provider_name.strip().lower()
    if key not in get_enabled_provider_ids():
        raise ValidationError({"provider": "This payment method is not available."})

    currency = (currency or "USD").strip().upper()
    if currency != "USD":
        raise ValidationError({"currency": "Only USD is supported for balance top-up."})

    _validate_topup_amount(amount, key)

    topup = BalanceTopUp.objects.create(
        user=user,
        amount=amount,
        currency=currency,
        status=BalanceTopUp.Status.PENDING,
    )

    prov = get_provider(key)
    idem_key = f"topup-{topup.public_id}-{key}"
    payment = Payment.objects.create(
        order=None,
        balance_top_up=topup,
        provider=key,
        amount=amount,
        currency=currency,
        status=Payment.Status.PENDING,
        idempotency_key=idem_key[:64],
    )

    success_url, cancel_url = _balance_topup_urls()
    description = f"Balance top-up {topup.public_id}"

    try:
        result = prov.create_invoice(
            reference_id=topup.public_id,
            amount=amount,
            currency=currency,
            idempotency_key=idem_key,
            order_description=description,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except RuntimeError:
        payment.status = Payment.Status.FAILED
        payment.provider_status = "invoice_error"
        payment.save(update_fields=["status", "provider_status", "updated_at"])
        topup.status = BalanceTopUp.Status.FAILED
        topup.save(update_fields=["status", "updated_at"])
        transaction.on_commit(
            lambda payment=payment, topup=topup: _notify_topup_event(
                payment=payment,
                topup=topup,
                success=False,
                status_text=Payment.Status.FAILED,
                reason="invoice_error",
            )
        )
        transaction.on_commit(
            lambda topup=topup, key=key, payment=payment: _notify_payment_error(
                provider_id=key,
                error_code="invoice_error_topup",
                error_message="Failed to create invoice for balance top-up.",
                context={
                    "topup_public_id": str(topup.public_id),
                    "payment_id": str(payment.pk),
                },
            )
        )
        raise

    payment.invoice_url = result.get("invoice_url") or ""
    ext_id = result.get("provider_payment_id")
    if ext_id:
        collision = (
            Payment.objects.filter(provider_payment_id=str(ext_id))
            .exclude(pk=payment.pk)
            .exists()
        )
        if not collision:
            payment.provider_payment_id = str(ext_id)
    payment.status = Payment.Status.PROCESSING
    payment.save(
        update_fields=["invoice_url", "provider_payment_id", "status", "updated_at"]
    )
    return payment


def acquire_webhook_lock(provider_key: str, ttl_seconds: int = 90) -> bool:
    cache_key = f"payment_ipn:{provider_key}"
    return cache.add(cache_key, 1, timeout=ttl_seconds)


def _payload_dedup_key(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@transaction.atomic
def _apply_balance_topup_if_paid(payment: Payment) -> bool:
    if not payment.balance_top_up_id:
        return False
    topup = (
        BalanceTopUp.objects.select_for_update()
        .filter(pk=payment.balance_top_up_id)
        .first()
    )
    if not topup:
        return False

    tx = create_wallet_transaction(
        user_id=topup.user_id,
        kind=WalletTransaction.Kind.TOPUP_CREDIT,
        source_type=WalletTransaction.SourceType.PAYMENT,
        source_id=str(payment.pk),
        amount=Decimal(topup.amount),
        currency=topup.currency,
        description=_wallet_description(
            kind=WalletTransaction.Kind.TOPUP_CREDIT,
            amount=Decimal(topup.amount),
            topup=topup,
        ),
        metadata={
            "payment_id": str(payment.pk),
            "balance_top_up_id": topup.pk,
            "balance_top_up_public_id": topup.public_id,
            "provider": payment.provider,
        },
    )
    if tx is None:
        return False

    if topup.status != BalanceTopUp.Status.COMPLETED:
        topup.status = BalanceTopUp.Status.COMPLETED
        topup.save(update_fields=["status", "updated_at"])
    transaction.on_commit(
        lambda payment=payment, topup=topup: _notify_topup_event(
            payment=payment,
            topup=topup,
            success=True,
            status_text=Payment.Status.SUCCEEDED,
        )
    )
    return True


def _payment_refund_source_id(refund: PaymentRefund) -> str:
    if refund.provider_refund_id:
        return refund.provider_refund_id
    return f"refund:{refund.pk}"


@transaction.atomic
def _apply_topup_refund(
    payment: Payment, *, amount: Decimal, reason: str, provider_refund_id: str = ""
) -> bool:
    if not payment.balance_top_up_id:
        return False
    topup = (
        BalanceTopUp.objects.select_for_update()
        .filter(pk=payment.balance_top_up_id)
        .first()
    )
    if not topup:
        return False

    refund, _ = PaymentRefund.objects.get_or_create(
        payment=payment,
        provider_refund_id=provider_refund_id or "",
        defaults={
            "amount": amount,
            "currency": payment.currency,
            "status": PaymentRefund.Status.SUCCEEDED,
            "reason": reason,
            "metadata": {"source": "provider_webhook"},
        },
    )
    if refund.status != PaymentRefund.Status.SUCCEEDED:
        refund.status = PaymentRefund.Status.SUCCEEDED
        refund.amount = amount
        refund.reason = reason
        refund.save(update_fields=["status", "amount", "reason", "updated_at"])

    tx = create_wallet_transaction(
        user_id=topup.user_id,
        kind=WalletTransaction.Kind.CHARGEBACK_DEBIT,
        source_type=WalletTransaction.SourceType.REFUND,
        source_id=_payment_refund_source_id(refund),
        amount=-abs(amount),
        currency=payment.currency,
        description=_wallet_description(
            kind=WalletTransaction.Kind.CHARGEBACK_DEBIT,
            amount=-abs(amount),
            topup=topup,
        ),
        metadata={
            "payment_id": str(payment.pk),
            "refund_id": str(refund.pk),
            "balance_top_up_public_id": topup.public_id,
            "provider_refund_id": provider_refund_id,
        },
    )
    return tx is not None


@transaction.atomic
def apply_provider_ipn_webhook(
    *, provider_key: str, payload: dict, signature_valid: bool
) -> tuple[int, Payment | None]:
    """
    Returns (http_status, payment_or_none). Always persist webhook log first.
    """
    pkey = (provider_key or "").strip().lower()
    log = PaymentWebhookLog.objects.create(
        raw_payload=payload,
        signature_valid=signature_valid,
    )

    if not signature_valid:
        log.processed_at = timezone.now()
        log.save(update_fields=["processed_at"])
        return 400, None

    prov = get_provider(pkey)
    parsed = prov.parse_webhook(payload)
    provider_payment_id = parsed.get("provider_payment_id") or ""
    provider_status = parsed.get("provider_status") or ""
    is_success = bool(parsed.get("is_success"))
    refund_id = str(payload.get("refund_id") or payload.get("refundId") or "").strip()
    if not refund_id and pkey == "rollypay":
        refund_id = str(payload.get("payment_id") or "").strip()

    payment = find_payment_for_provider_ipn(payload, pkey)
    if not payment:
        logger.warning(
            "payments_webhook_unknown_payment provider={} payload_keys={}",
            pkey,
            list(payload.keys()),
        )
        log.processed_at = timezone.now()
        log.save(update_fields=["processed_at"])
        return 200, None

    log.payment = payment
    log.save(update_fields=["payment"])

    dedup_key = _payload_dedup_key(payload)
    if not acquire_webhook_lock(dedup_key):
        logger.info("payments_webhook_duplicate_payload hash={}", dedup_key[:16])
        log.processed_at = timezone.now()
        log.save(update_fields=["processed_at"])
        return 200, payment

    if payment.status == Payment.Status.SUCCEEDED and is_success:
        log.processed_at = timezone.now()
        log.save(update_fields=["processed_at"])
        return 200, payment

    payment.provider_status = provider_status
    payment.webhook_received_at = timezone.now()
    new_status = _map_provider_status_to_payment(pkey, provider_status, is_success)

    ext_id = provider_payment_id
    if ext_id and not payment.provider_payment_id:
        if (
            not Payment.objects.filter(provider_payment_id=ext_id)
            .exclude(pk=payment.pk)
            .exists()
        ):
            payment.provider_payment_id = ext_id

    payment.status = new_status
    payment.save(
        update_fields=[
            "provider_status",
            "webhook_received_at",
            "status",
            "provider_payment_id",
            "updated_at",
        ]
    )

    if is_success:
        if payment.order_id:
            order = (
                Order.objects.select_for_update().filter(pk=payment.order_id).first()
            )
            if order and order.status == Order.Status.AWAITING_PAYMENT:
                try:
                    with transaction.atomic():
                        process_paid_order(order)
                except Exception:
                    logger.exception(
                        "payments_webhook_process_paid_failed order_id={}", order.pk
                    )
                    transaction.on_commit(
                        lambda payment=payment, order=order: _notify_payment_error(
                            provider_id=payment.provider,
                            error_code="webhook_process_paid_failed",
                            error_message="Failed to process paid order from webhook.",
                            context={
                                "order_public_id": str(order.public_id),
                                "payment_id": str(payment.pk),
                            },
                        )
                    )
        elif payment.balance_top_up_id:
            try:
                with transaction.atomic():
                    _apply_balance_topup_if_paid(payment)
            except Exception:
                logger.exception(
                    "payments_webhook_balance_topup_failed payment_id={}", payment.pk
                )
                transaction.on_commit(
                    lambda payment=payment: _notify_payment_error(
                        provider_id=payment.provider,
                        error_code="webhook_balance_topup_failed",
                        error_message="Failed to apply successful top-up from webhook.",
                        context={
                            "payment_id": str(payment.pk),
                            "topup_id": str(payment.balance_top_up_id or ""),
                        },
                    )
                )
    elif new_status == Payment.Status.REFUNDED:
        try:
            with transaction.atomic():
                PaymentRefund.objects.get_or_create(
                    payment=payment,
                    provider_refund_id=refund_id or "",
                    defaults={
                        "amount": payment.amount,
                        "currency": payment.currency,
                        "status": PaymentRefund.Status.SUCCEEDED,
                        "reason": provider_status or "provider_refund",
                        "metadata": {"payload": payload},
                    },
                )
                if payment.balance_top_up_id:
                    _apply_topup_refund(
                        payment,
                        amount=Decimal(payment.amount),
                        reason=provider_status or "provider_refund",
                        provider_refund_id=refund_id,
                    )
        except Exception:
            logger.exception("payments_webhook_refund_failed payment_id={}", payment.pk)
            transaction.on_commit(
                lambda payment=payment: _notify_payment_error(
                    provider_id=payment.provider,
                    error_code="webhook_refund_failed",
                    error_message="Failed to process refund from webhook.",
                    context={
                        "payment_id": str(payment.pk),
                        "topup_id": str(payment.balance_top_up_id or ""),
                    },
                )
            )

    if not is_success and new_status == Payment.Status.FAILED and not payment.balance_top_up_id:
        transaction.on_commit(
            lambda payment=payment, provider_status=provider_status: _notify_provider_payment_failed(
                payment=payment,
                provider_status=provider_status,
            )
        )

    if (
        not is_success
        and payment.balance_top_up_id
        and new_status
        in (
            Payment.Status.FAILED,
            Payment.Status.EXPIRED,
            Payment.Status.REFUNDED,
        )
    ):
        bt = (
            BalanceTopUp.objects.filter(pk=payment.balance_top_up_id)
            .select_for_update()
            .first()
        )
        if bt:
            if bt.status == BalanceTopUp.Status.PENDING:
                bt.status = BalanceTopUp.Status.FAILED
                bt.save(update_fields=["status", "updated_at"])
            if new_status in (Payment.Status.FAILED, Payment.Status.REFUNDED):
                transaction.on_commit(
                    lambda payment=payment,
                    bt=bt,
                    new_status=new_status,
                    provider_status=provider_status: _notify_topup_event(
                        payment=payment,
                        topup=bt,
                        success=False,
                        status_text=new_status,
                        reason=provider_status,
                    )
                )

    log.processed_at = timezone.now()
    log.save(update_fields=["processed_at"])
    return 200, payment


def apply_nowpayments_webhook(
    *, payload: dict, signature_valid: bool
) -> tuple[int, Payment | None]:
    return apply_provider_ipn_webhook(
        provider_key="nowpayments", payload=payload, signature_valid=signature_valid
    )


def apply_rollypay_webhook(
    *, payload: dict, signature_valid: bool
) -> tuple[int, Payment | None]:
    return apply_provider_ipn_webhook(
        provider_key="rollypay", payload=payload, signature_valid=signature_valid
    )


def apply_enot_webhook(
    *, payload: dict, signature_valid: bool
) -> tuple[int, Payment | None]:
    return apply_provider_ipn_webhook(
        provider_key="enot", payload=payload, signature_valid=signature_valid
    )


def reconcile_order_payment_on_return(
    *, order_public_id: int, query_params: dict[str, str]
) -> Payment | None:
    """
    Best-effort payment reconciliation on provider return URL.
    Security model: never trust query params alone; fetch authoritative status from provider API.
    """
    order = Order.objects.filter(public_id=order_public_id).first()
    if not order or order.status != Order.Status.AWAITING_PAYMENT:
        return None

    payment = (
        Payment.objects.filter(
            order=order,
            status__in=[Payment.Status.PENDING, Payment.Status.PROCESSING],
        )
        .order_by("-created_at")
        .first()
    )
    if not payment:
        return None

    provider_key = (payment.provider or "").strip().lower()
    if provider_key not in ("nowpayments", "rollypay", "enot"):
        return payment

    prov = get_provider(provider_key)
    fetcher = getattr(prov, "fetch_payment_status", None)
    if not callable(fetcher):
        return payment

    pid = (
        query_params.get("NP_id")
        or query_params.get("np_id")
        or query_params.get("payment_id")
        or payment.provider_payment_id
        or ""
    )
    pid = str(pid).strip()
    if not pid:
        return payment

    provider_payload = fetcher(provider_payment_id=pid)
    provider_payload["payment_id"] = provider_payload.get("payment_id") or pid
    provider_payload["order_id"] = provider_payload.get("order_id") or str(
        order_public_id
    )
    _, refreshed = apply_provider_ipn_webhook(
        provider_key=provider_key,
        payload=provider_payload,
        signature_valid=True,
    )
    return refreshed or payment


def poll_awaiting_order_payments(*, batch_limit: int = 200) -> int:
    """
    Fallback reconciliation for awaiting-payment orders.
    Safe path: only applies provider-authoritative status from provider API.
    """
    rows = list(
        Payment.objects.select_related("order")
        .filter(
            order__isnull=False,
            order__status=Order.Status.AWAITING_PAYMENT,
            status__in=[Payment.Status.PENDING, Payment.Status.PROCESSING],
            provider__in=["nowpayments", "rollypay", "enot"],
        )
        .order_by("created_at")[: max(int(batch_limit or 200), 1)]
    )
    if not rows:
        return 0
    reconciled = 0
    for payment in rows:
        prov = get_provider((payment.provider or "").strip().lower())
        fetcher = getattr(prov, "fetch_payment_status", None)
        if not callable(fetcher):
            continue
        pid = str(payment.provider_payment_id or "").strip()
        if not pid:
            continue
        try:
            payload = fetcher(provider_payment_id=pid)
            payload["payment_id"] = payload.get("payment_id") or pid
            payload["order_id"] = payload.get("order_id") or str(
                payment.order.public_id
            )
            before = payment.order.status
            _, refreshed = apply_provider_ipn_webhook(
                provider_key=(payment.provider or "").strip().lower(),
                payload=payload,
                signature_valid=True,
            )
            target_payment = refreshed or payment
            target_order = (
                target_payment.order
                if target_payment and target_payment.order_id
                else payment.order
            )
            if target_order and before != target_order.status:
                reconciled += 1
        except Exception:
            logger.exception(
                "poll_awaiting_order_payments_failed payment_id={}",
                payment.pk,
            )
            transaction.on_commit(
                lambda payment=payment: _notify_payment_error(
                    provider_id=payment.provider,
                    error_code="poll_reconcile_failed",
                    error_message="Failed to reconcile payment status via provider API.",
                    context={
                        "payment_id": str(payment.pk),
                        "order_public_id": str(
                            getattr(getattr(payment, "order", None), "public_id", "")
                        ),
                    },
                )
            )
    return reconciled
