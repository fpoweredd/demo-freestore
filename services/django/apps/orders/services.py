from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
import re

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone as django_timezone
from loguru import logger

from apps.accounts.models import AccountProfile
from apps.catalog.models import DigitalItem, Product, ProductCard, ProductInputField
from apps.catalog.visibility import purchasable_products
from apps.core.bot_api_client import (
    post_manual_order_notify,
    post_order_notify,
    post_preorder_fulfilled_notify,
    post_preorder_paid_notify,
)
from apps.payments.internal_balance import INTERNAL_BALANCE_PROVIDER_ID
from apps.payments.models import Payment
from apps.payments.providers import get_provider
from apps.payments.providers.registry import get_product_provider_buttons

from .models import (
    ManualDispatchLog,
    Order,
    OrderItem,
    OrderItemDigitalItem,
    OrderItemInput,
    OrderStatusLog,
    OrderTelegramNotifyLog,
    PreOrder,
)

TELEGRAM_HANDLE_INPUT_KEY = "telegram_handle"
TELEGRAM_HANDLE_INPUT_LABEL = "Telegram"
TELEGRAM_NOTIFY_RETRY_DELAYS_SECONDS = (60, 300, 900, 3600, 10800)


def _create_tg_notify_log(
    *, order: Order, kind: str, payload: dict[str, Any]
) -> OrderTelegramNotifyLog:
    return OrderTelegramNotifyLog.objects.create(
        order=order,
        kind=kind,
        status=OrderTelegramNotifyLog.Status.QUEUED,
        attempts=0,
        max_attempts=5,
        payload_snapshot=payload,
    )


def _mark_tg_notify_log_sent(
    log: OrderTelegramNotifyLog, response: dict[str, Any] | None = None
) -> None:
    log.status = OrderTelegramNotifyLog.Status.SENT
    log.attempts = int(log.attempts or 0) + 1
    log.last_attempt_at = datetime.now(timezone.utc)
    log.sent_at = datetime.now(timezone.utc)
    log.error_message = ""
    log.response_snapshot = response or {}
    log.save(
        update_fields=[
            "status",
            "attempts",
            "last_attempt_at",
            "sent_at",
            "error_message",
            "response_snapshot",
            "updated_at",
        ]
    )


def _mark_tg_notify_log_failed(log: OrderTelegramNotifyLog, error_message: str) -> None:
    log.status = OrderTelegramNotifyLog.Status.FAILED
    log.attempts = int(log.attempts or 0) + 1
    log.last_attempt_at = datetime.now(timezone.utc)
    log.error_message = (error_message or "Telegram notify failed").strip()[:2000]
    log.save(
        update_fields=[
            "status",
            "attempts",
            "last_attempt_at",
            "error_message",
            "updated_at",
        ]
    )


@dataclass
class QuoteItem:
    product: Product
    quantity: int
    unit_price: Decimal
    total_price: Decimal
    validated_inputs: dict[str, str]
    available_stock: int


def _validate_field_value(field: ProductInputField, value: str) -> str:
    value = (value or "").strip()

    if field.is_required and not value:
        raise ValidationError(
            {
                field.key: ValidationError(
                    "This field is required.", code="required"
                )
            }
        )

    if not value:
        return value

    if field.field_type == ProductInputField.FieldType.EMAIL and "@" not in value:
        raise ValidationError(
            {
                field.key: ValidationError(
                    "Enter a valid email.", code="invalid_email"
                )
            }
        )

    if field.regex:
        try:
            pattern = re.compile(field.regex)
        except re.error as exc:
            raise ValidationError(
                {
                    field.key: ValidationError(
                        "Invalid validation rule in product settings.",
                        code="invalid_regex_pattern",
                    )
                }
            ) from exc
        if not pattern.fullmatch(value):
            raise ValidationError(
                {
                    field.key: ValidationError(
                        "Value does not match the required format.",
                        code="regex",
                    )
                }
            )

    if field.field_type == ProductInputField.FieldType.NUMBER:
        try:
            numeric = Decimal(value)
        except InvalidOperation as exc:
            raise ValidationError(
                {
                    field.key: ValidationError(
                        "Enter a valid number.", code="invalid_number"
                    )
                }
            ) from exc

        if field.min_value is not None and numeric < field.min_value:
            raise ValidationError(
                {
                    field.key: ValidationError(
                        "Value is below the minimum.", code="min_value"
                    )
                }
            )

        if field.max_value is not None and numeric > field.max_value:
            raise ValidationError(
                {
                    field.key: ValidationError(
                        "Value is above the maximum.", code="max_value"
                    )
                }
            )

    return value


def validate_manual_inputs(
    product_card: ProductCard, input_payload: dict[str, str]
) -> dict[str, str]:
    field_map = {
        field.key: field
        for field in product_card.input_fields.filter(is_active=True).order_by(
            "sort_order", "id"
        )
    }
    validated: dict[str, str] = {}
    errors: dict[str, list[ValidationError]] = {}

    for key, field in field_map.items():
        raw_value = input_payload.get(key, "")
        try:
            validated[key] = _validate_field_value(field, raw_value)
        except ValidationError as exc:
            errors[key] = exc.error_list

    if bool(getattr(product_card, "include_telegram_handle_field", False)):
        raw_tg = str(input_payload.get(TELEGRAM_HANDLE_INPUT_KEY, "") or "").strip()
        normalized_tg = _normalize_telegram_handle(raw_tg)
        validated[TELEGRAM_HANDLE_INPUT_KEY] = normalized_tg
        if normalized_tg and len(normalized_tg) > 64:
            errors[TELEGRAM_HANDLE_INPUT_KEY] = [
                ValidationError(
                    "Telegram handle is too long (max 64 characters).",
                    code="max_length",
                )
            ]

    unknown_keys = set(input_payload.keys()) - set(field_map.keys())
    if bool(getattr(product_card, "include_telegram_handle_field", False)):
        unknown_keys.discard(TELEGRAM_HANDLE_INPUT_KEY)
    if unknown_keys:
        for key in sorted(unknown_keys):
            errors[key] = [
                ValidationError("Unknown order field.", code="unknown_field")
            ]

    if errors:
        raise ValidationError(errors)

    return validated


def _determine_unit_price(
    product: Product, validated_inputs: dict[str, str]
) -> Decimal:
    if product.product_card.fulfillment_mode == ProductCard.FulfillmentMode.MANUAL:
        amount = validated_inputs.get("amount")
        if amount:
            return Decimal(amount)
    return product.price


def _format_decimal(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _order_user_public_id(order: Order) -> str:
    if not order.user_id or not getattr(order, "user", None):
        return "-"
    profile = getattr(order.user, "account_profile", None)
    if profile is None:
        return "-"
    return str(profile.public_id or "-")


def _order_user_profile(order: Order):
    if not order.user_id or not getattr(order, "user", None):
        return None
    return getattr(order.user, "account_profile", None)


def _order_user_email(order: Order) -> str:
    if not order.user_id or not getattr(order, "user", None):
        return "-"
    return (order.user.email or "").strip() or "-"


def _normalize_telegram_handle(value: str) -> str:
    normalized = (value or "").strip()
    while normalized.startswith("@"):
        normalized = normalized[1:].strip()
    return normalized


def _order_tg_handle_from_inputs(order: Order) -> str:
    for item in order.items.select_related("product__product_card").all():
        payload = item.input_payload or {}
        if not isinstance(payload, dict):
            continue
        value = _normalize_telegram_handle(
            str(payload.get(TELEGRAM_HANDLE_INPUT_KEY) or "")
        )
        if value:
            return f"@{value}"
    return ""


def _build_order_item_sku_line(item: OrderItem) -> str:
    from apps.catalog.sku_display import build_selected_sku_rows, sku_row_values

    card = item.product.product_card
    parts: list[str] = [card.name]
    rows = build_selected_sku_rows(
        product_id=item.product_id,
        price=item.unit_price,
        attributes=item.product.attributes or {},
        selector_axes=card.selector_axes or [],
        ui_labels=card.ui_labels or {},
    )
    parts.extend(sku_row_values(rows))
    return " / ".join(parts)


def _sanitize_utm_params(raw: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            k = str(key or "").strip()
            v = str(value or "").strip()
            if k and v:
                result[k] = v
        return result

    if isinstance(raw, list):
        for index, value in enumerate(raw):
            if isinstance(value, dict):
                for key, dict_value in value.items():
                    k = str(key or "").strip()
                    v = str(dict_value or "").strip()
                    if k and v:
                        result[k] = v
            else:
                text = str(value or "").strip()
                if text:
                    result[f"item_{index}"] = text
    return result


def _order_payment_method(order: Order) -> str:
    payment = (
        Payment.objects.filter(order=order, status=Payment.Status.SUCCEEDED)
        .order_by("-created_at")
        .only("provider")
        .first()
    )
    if payment is None:
        payment = (
            Payment.objects.filter(order=order)
            .order_by("-created_at")
            .only("provider")
            .first()
        )
    if payment is None:
        return "-"
    provider = (payment.provider or "").strip()
    if provider == INTERNAL_BALANCE_PROVIDER_ID:
        return "balance"
    return provider or "-"


def _build_order_notify_payload(order: Order) -> dict:
    profile = _order_user_profile(order)
    role_value = str(getattr(profile, "role", "") or "").strip()
    tg_id = getattr(profile, "tg_id", None)
    tg_username = str(getattr(profile, "tg_username", "") or "").strip()
    telegram_handle = str(getattr(profile, "telegram_handle", "") or "").strip()
    tg_auth = None
    if tg_id and tg_username:
        normalized = tg_username.lstrip("@")
        tg_auth = f"@{normalized} ({tg_id})"
    tg_handler = None
    if not tg_auth and telegram_handle:
        tg_handler = f"@{telegram_handle.lstrip('@')}"
    if not tg_auth and not tg_handler:
        fallback_tg = _order_tg_handle_from_inputs(order)
        if fallback_tg:
            tg_handler = fallback_tg

    user_email = _order_user_email(order)
    order_email = (order.guest_email or "").strip() or "-"
    wallet_balance_after = "-"
    if profile is not None:
        wallet_balance_after = _format_decimal(
            Decimal(profile.balance or Decimal("0.00"))
        )

    items_payload = []
    for item in order.items.select_related("product__product_card").all():
        input_payload = item.input_payload or {}
        input_fields = (
            ProductInputField.objects.filter(
                product_card_id=item.product.product_card_id,
                is_active=True,
            )
            .only("key", "label", "field_type", "sort_order")
            .order_by("sort_order", "id")
        )
        labels_by_key = {
            str(field.key): str(field.label or field.key) for field in input_fields
        }
        labels_by_key.setdefault(TELEGRAM_HANDLE_INPUT_KEY, TELEGRAM_HANDLE_INPUT_LABEL)
        labeled_params: list[dict[str, str]] = []
        used_keys: set[str] = set()
        if isinstance(input_payload, dict):
            # Keep UI order: ProductInputField.sort_order, then id.
            for field in input_fields:
                key = str(field.key)
                if key not in input_payload:
                    continue
                value = str(input_payload.get(key) or "").strip()
                if not value:
                    continue
                labeled_params.append(
                    {
                        "key": key,
                        "label": labels_by_key.get(key, key),
                        "value": value,
                    }
                )
                used_keys.add(key)

            # Fallback for legacy keys not present in ProductInputField.
            for key in sorted(input_payload.keys()):
                if key in used_keys:
                    continue
                value = str(input_payload.get(key) or "").strip()
                if not value:
                    continue
                labeled_params.append(
                    {
                        "key": str(key),
                        "label": str(key),
                        "value": value,
                    }
                )
        items_payload.append(
            {
                "product_name": item.product.product_card.name,
                "quantity": int(item.quantity),
                "sku_params": input_payload,
                "sku_params_labeled": labeled_params,
                "sku_line": _build_order_item_sku_line(item),
            }
        )
    return {
        "order_public_id": int(order.public_id),
        "user_public_id": _order_user_public_id(order),
        "user_email": user_email,
        "order_email": order_email,
        "total_rub": _format_decimal(Decimal(order.total)),
        "payment_method": _order_payment_method(order),
        "wallet_balance_after_rub": wallet_balance_after,
        "tg_auth": tg_auth,
        "tg_handler": tg_handler,
        "role": role_value if role_value and role_value != "customer" else "",
        "reg_geo": str(getattr(profile, "ip_geo", "") or "").strip() if profile else "",
        "locale": str(getattr(profile, "locale", "") or "").strip() if profile else "",
        "utm_params": _sanitize_utm_params(
            getattr(profile, "utm_params", {}) if profile else (order.utm_params or {})
        ),
        "items": items_payload,
    }


def notify_telegram_bot_new_order(order: Order) -> None:
    if order.status != Order.Status.COMPLETED:
        return
    # Orders that went through preorder flow must stay in preorder topic only.
    if PreOrder.objects.filter(order=order).exists():
        return

    dedup_key = f"order_tg_notify_completed:{order.public_id}"
    if not cache.add(dedup_key, 1, timeout=30 * 24 * 3600):
        return

    payload = _build_order_notify_payload(order)
    log = _create_tg_notify_log(
        order=order, kind=OrderTelegramNotifyLog.Kind.NEW_ORDER, payload=payload
    )
    if post_order_notify(payload):
        _mark_tg_notify_log_sent(log)
    else:
        _mark_tg_notify_log_failed(log, "Failed to send NEW_ORDER")


def _build_preorder_paid_notify_payload(*, order: Order, preorder: PreOrder) -> dict:
    payload = _build_order_notify_payload(order)
    payload["preorder_public_id"] = int(preorder.public_id)
    payload["preorder_status"] = preorder.status
    base = str(getattr(settings, "PUBLIC_SITE_URL", "http://127.0.0.1:8000")).rstrip(
        "/"
    )
    payload["admin_upload_url"] = (
        f"{base}{reverse('admin:catalog_digitalitem_bulk_upload')}?product_id={preorder.product_id}"
    )
    return payload


def notify_telegram_bot_preorder_paid(order: Order) -> None:
    preorder = PreOrder.objects.filter(order=order).first()
    if preorder is None or preorder.status != PreOrder.Status.PAID:
        return
    dedup_key = f"preorder_tg_notify_paid:{preorder.public_id}"
    if not cache.add(dedup_key, 1, timeout=30 * 24 * 3600):
        return
    payload = _build_preorder_paid_notify_payload(order=order, preorder=preorder)
    log = _create_tg_notify_log(
        order=order, kind=OrderTelegramNotifyLog.Kind.PREORDER_PAID, payload=payload
    )
    resp = post_preorder_paid_notify(payload)
    if resp and resp.get("ok") is True:
        _mark_tg_notify_log_sent(log, response=resp)
    else:
        _mark_tg_notify_log_failed(log, "Failed to send PREORDER_PAID")


def _build_preorder_fulfilled_notify_payload(
    *, order: Order, preorder: PreOrder
) -> dict:
    payload = _build_order_notify_payload(order)
    payload["preorder_public_id"] = int(preorder.public_id)
    payload["preorder_status"] = preorder.status
    return payload


def notify_telegram_bot_preorder_fulfilled(
    order: Order, preorder_public_id: int
) -> None:
    preorder = PreOrder.objects.filter(
        order=order, public_id=preorder_public_id
    ).first()
    if preorder is None or preorder.status != PreOrder.Status.FULFILLED:
        return
    dedup_key = f"preorder_tg_notify_fulfilled:{preorder.public_id}"
    if not cache.add(dedup_key, 1, timeout=30 * 24 * 3600):
        return
    payload = _build_preorder_fulfilled_notify_payload(order=order, preorder=preorder)
    paid_log = (
        OrderTelegramNotifyLog.objects.filter(
            order=order,
            kind=OrderTelegramNotifyLog.Kind.PREORDER_PAID,
            status=OrderTelegramNotifyLog.Status.SENT,
        )
        .filter(payload_snapshot__preorder_public_id=int(preorder_public_id))
        .order_by("-sent_at", "-id")
        .first()
    )
    if paid_log and isinstance(paid_log.response_snapshot, dict):
        snap = paid_log.response_snapshot
        text = snap.get("text")
        chat_id = snap.get("chat_id")
        message_id = snap.get("message_id")
        if (
            text
            and str(text).strip()
            and chat_id is not None
            and message_id is not None
        ):
            payload["edit_chat_id"] = int(chat_id)
            payload["edit_message_id"] = int(message_id)
            payload["previous_text"] = str(text)
    log = _create_tg_notify_log(
        order=order,
        kind=OrderTelegramNotifyLog.Kind.PREORDER_FULFILLED,
        payload=payload,
    )
    if post_preorder_fulfilled_notify(payload):
        _mark_tg_notify_log_sent(log)
    else:
        _mark_tg_notify_log_failed(log, "Failed to send PREORDER_FULFILLED")


def _wallet_balance_for_user(user) -> Decimal:
    if not user or not getattr(user, "is_authenticated", False):
        return Decimal("0.00")
    profile = getattr(user, "account_profile", None)
    if profile is None:
        profile, _ = AccountProfile.objects.get_or_create(user=user)
    return Decimal(profile.balance or Decimal("0.00"))


def _available_stock_for_product(product: Product) -> int:
    if product.product_card.fulfillment_mode == ProductCard.FulfillmentMode.MANUAL:
        return 999999
    return int(
        DigitalItem.objects.filter(
            product_id=product.id,
            is_used=False,
            reserved_at__isnull=True,
        ).count()
    )


def _validate_quote_item_stock(product: Product, quantity: int) -> int:
    available_stock = _available_stock_for_product(product)
    if (
        product.product_card.fulfillment_mode == ProductCard.FulfillmentMode.INSTANT
        and quantity > available_stock
    ):
        if not bool(getattr(product.product_card, "preorders_enabled", True)):
            raise ValidationError(
                {
                    "product_id": ValidationError(
                        "Out of stock and preorders are disabled for this product.",
                        code="out_of_stock_preorders_disabled",
                    )
                }
            )
    return available_stock


def _normalize_order_quantity_for_card(
    *, product_card: ProductCard, requested_quantity: int
) -> int:
    min_qty = max(int(getattr(product_card, "min_order_quantity", 1) or 1), 1)
    max_qty = max(int(getattr(product_card, "max_order_quantity", 1) or 1), min_qty)
    default_qty = int(
        getattr(product_card, "default_order_quantity", min_qty) or min_qty
    )
    default_qty = max(min_qty, min(default_qty, max_qty))
    if not bool(getattr(product_card, "quantity_selection_enabled", False)):
        return default_qty
    qty = int(requested_quantity or default_qty)
    if qty < min_qty or qty > max_qty:
        raise ValidationError(
            {
                "quantity": ValidationError(
                    f"Quantity must be between {min_qty} and {max_qty}.",
                    code="quantity_out_of_range",
                )
            }
        )
    return qty


def log_order_status_change(
    order: Order, *, from_status: str, to_status: str, actor: str = "", note: str = ""
) -> OrderStatusLog:
    return OrderStatusLog.objects.create(
        order=order,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        note=note,
    )


def transition_order_status(
    order: Order, to_status: str, *, actor: str = "", note: str = ""
) -> Order:
    from_status = order.status or ""
    if from_status == to_status:
        return order
    order.status = to_status
    order.save(update_fields=["status", "updated_at"])
    log_order_status_change(
        order,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        note=note,
    )
    return order


def build_quote_items(items_data: list[dict]) -> list[QuoteItem]:
    quote_items: list[QuoteItem] = []
    for row in items_data:
        product = purchasable_products().select_related("product_card").get(
            id=row["product_id"],
        )
        requested_quantity = int(row.get("quantity", 1) or 1)
        quantity = _normalize_order_quantity_for_card(
            product_card=product.product_card,
            requested_quantity=requested_quantity,
        )
        input_payload = row.get("inputs") or {}

        validated_inputs = {}
        if product.product_card.fulfillment_mode == ProductCard.FulfillmentMode.MANUAL:
            validated_inputs = validate_manual_inputs(
                product.product_card, input_payload
            )

        unit_price = _determine_unit_price(product, validated_inputs)
        total_price = unit_price * quantity
        available_stock = _validate_quote_item_stock(product, quantity)
        quote_items.append(
            QuoteItem(
                product=product,
                quantity=quantity,
                unit_price=unit_price,
                total_price=total_price,
                validated_inputs=validated_inputs,
                available_stock=available_stock,
            )
        )
    return quote_items


def build_quote_response(items_data: list[dict], currency: str = "USD") -> dict:
    quote_items = build_quote_items(items_data)
    total = sum((row.total_price for row in quote_items), Decimal("0.00"))
    return {
        "currency": currency,
        "subtotal": _format_decimal(total),
        "total": _format_decimal(total),
        "items": [
            {
                "product_id": row.product.id,
                "product_public_id": row.product.id,
                "product_card": row.product.product_card.name,
                "product_card_slug": row.product.product_card.slug,
                "quantity": row.quantity,
                "unit_price": _format_decimal(row.unit_price),
                "total_price": _format_decimal(row.total_price),
                "inputs": row.validated_inputs,
                "fulfillment_mode": row.product.product_card.fulfillment_mode,
                "available_stock": row.available_stock,
                "is_preorder": (
                    row.product.product_card.fulfillment_mode
                    == ProductCard.FulfillmentMode.INSTANT
                    and row.quantity > row.available_stock
                ),
            }
            for row in quote_items
        ],
    }


def build_checkout_payment_context(*, total: Decimal, user) -> dict:
    wallet_balance = _wallet_balance_for_user(user)
    is_authenticated = bool(user and getattr(user, "is_authenticated", False))
    options: list[dict] = []

    wallet_available = is_authenticated and wallet_balance > 0
    wallet_can_pay = is_authenticated and wallet_balance >= total
    options.append(
        {
            "id": INTERNAL_BALANCE_PROVIDER_ID,
            "label": "Wallet balance",
            "kind": "wallet",
            "available": wallet_available,
            "direct_pay_available": wallet_can_pay,
            "min_order_amount": _format_decimal(Decimal("0.00")),
            "wallet_balance": _format_decimal(wallet_balance),
            "shortfall": _format_decimal(max(total - wallet_balance, Decimal("0.00"))),
        }
    )

    min_topup_amount: Decimal | None = None
    direct_provider_available = False
    provider_buttons = get_product_provider_buttons()
    for button in provider_buttons:
        provider = get_provider(button["id"])
        direct_min_amount = max(
            Decimal(str(button.get("min_product_amount") or "0")),
            Decimal(str(provider.min_amount)),
        )
        direct_pay_available = total >= direct_min_amount
        if direct_pay_available:
            direct_provider_available = True
        else:
            if min_topup_amount is None or direct_min_amount < min_topup_amount:
                min_topup_amount = direct_min_amount
        options.append(
            {
                "id": button["id"],
                "label": button["label"],
                "kind": "external",
                "available": True,
                "direct_pay_available": direct_pay_available,
                "min_order_amount": _format_decimal(direct_min_amount),
                "requires_wallet_topup": not direct_pay_available,
                "suggested_topup_amount": _format_decimal(direct_min_amount)
                if not direct_pay_available
                else None,
            }
        )

    recommended_action = "direct_payment"
    if wallet_can_pay:
        recommended_action = "wallet_payment"
    elif direct_provider_available:
        recommended_action = "direct_payment"
    elif is_authenticated and min_topup_amount is not None:
        recommended_action = "wallet_topup_required"
    elif not is_authenticated and min_topup_amount is not None:
        recommended_action = "auth_required_for_wallet_topup"
    elif not provider_buttons:
        recommended_action = "no_payment_methods"

    return {
        "wallet_balance": _format_decimal(wallet_balance),
        "wallet_can_pay": wallet_can_pay,
        "is_authenticated": is_authenticated,
        "recommended_action": recommended_action,
        "suggested_topup_amount": _format_decimal(min_topup_amount)
        if min_topup_amount is not None
        else None,
        "payment_methods": options,
    }


def build_checkout_quote(
    *, items_data: list[dict], currency: str = "USD", user=None
) -> dict:
    quote = build_quote_response(items_data=items_data, currency=currency)
    total = Decimal(quote["total"])
    quote["checkout"] = build_checkout_payment_context(total=total, user=user)
    return quote


def _reserve_digital_items_for_order_item(order_item: OrderItem, quantity: int) -> None:
    product = order_item.product
    if product.product_card.fulfillment_mode != ProductCard.FulfillmentMode.INSTANT:
        return
    if not bool(getattr(product.product_card, "use_reservations", False)):
        return

    items = list(
        DigitalItem.objects.select_for_update()
        .filter(
            product_id=product.id,
            is_used=False,
            reserved_at__isnull=True,
        )
        .order_by("id")[:quantity]
    )
    if len(items) < quantity:
        raise ValidationError(
            {
                "product_id": ValidationError(
                    "Not enough instant stock to reserve.", code="reserve_failed"
                )
            }
        )

    now = datetime.now(timezone.utc)
    for item in items:
        item.reserved_at = now
    DigitalItem.objects.bulk_update(items, ["reserved_at", "updated_at"])
    OrderItemDigitalItem.objects.bulk_create(
        [
            OrderItemDigitalItem(order_item=order_item, digital_item=item)
            for item in items
        ]
    )
    product.stock_count = DigitalItem.objects.filter(
        product_id=product.id,
        is_used=False,
        reserved_at__isnull=True,
    ).count()
    product.save(update_fields=["stock_count", "updated_at"])


@transaction.atomic
def create_order_from_quote(
    items_data: list[dict],
    guest_email: str = "",
    currency: str = "USD",
    user=None,
    idempotency_key: str = "",
    utm_params: dict[str, str] | None = None,
) -> Order:
    if not user and not (guest_email or "").strip():
        raise ValidationError(
            {
                "guest_email": ValidationError(
                    "Enter an email to receive the order.", code="required"
                )
            }
        )

    key = (idempotency_key or "").strip()
    if key:
        existing = Order.objects.filter(checkout_idempotency_key=key).first()
        if existing:
            return existing

    quote_items = build_quote_items(items_data)
    total = sum((row.total_price for row in quote_items), Decimal("0.00"))
    order = Order.objects.create(
        user=user,
        guest_email=guest_email,
        checkout_idempotency_key=key or None,
        currency=currency,
        total=total,
        status=Order.Status.AWAITING_PAYMENT,
        utm_params=_sanitize_utm_params(utm_params or {}),
    )
    log_order_status_change(
        order,
        from_status="",
        to_status=Order.Status.AWAITING_PAYMENT,
        actor="checkout",
        note="Order created from checkout quote.",
    )

    for row in quote_items:
        order_item = OrderItem.objects.create(
            order=order,
            product=row.product,
            quantity=row.quantity,
            unit_price=row.unit_price,
            total_price=row.total_price,
            input_payload=row.validated_inputs,
        )
        if row.validated_inputs:
            field_map = {
                field.key: field
                for field in row.product.product_card.input_fields.filter(
                    is_active=True, key__in=row.validated_inputs.keys()
                )
            }
            OrderItemInput.objects.bulk_create(
                [
                    OrderItemInput(
                        order_item=order_item, input_field=field_map[key], value=value
                    )
                    for key, value in row.validated_inputs.items()
                    if key in field_map
                ]
            )
        _reserve_digital_items_for_order_item(order_item, row.quantity)

        if (
            order_item.product.product_card.fulfillment_mode
            == ProductCard.FulfillmentMode.INSTANT
            and int(row.quantity) > int(row.available_stock)
        ):
            # Preorder queue item tied to this checkout order.
            PreOrder.objects.create(
                order=order,
                user=user
                if user and getattr(user, "is_authenticated", False)
                else None,
                guest_email=guest_email or "",
                product=row.product,
                quantity=int(row.quantity),
                input_payload=row.validated_inputs,
                utm_params=_sanitize_utm_params(utm_params or {}),
                status=PreOrder.Status.PENDING,
            )

    return order


@transaction.atomic
def fulfill_waiting_stock_orders_for_product(
    *, product: Product, batch_limit: int = 50
) -> int:
    """
    Allocate newly available DigitalItems to oldest paid orders waiting for stock.
    Returns number of orders that became COMPLETED.
    """
    completed = 0
    if product.product_card.fulfillment_mode != ProductCard.FulfillmentMode.INSTANT:
        return 0

    # PostgreSQL does not allow SELECT ... FOR UPDATE with DISTINCT.
    # We first collect distinct candidate ids, then lock concrete rows by ids.
    candidate_order_ids = list(
        Order.objects.filter(
            status__in=[
                Order.Status.WAITING_STOCK,
                Order.Status.PARTIALLY_FULFILLED,
            ],
            items__product=product,
        )
        .order_by("created_at")
        .values_list("id", flat=True)
        .distinct()[:batch_limit]
    )
    if not candidate_order_ids:
        return 0

    orders = list(
        Order.objects.select_for_update()
        .filter(id__in=candidate_order_ids)
        .order_by("created_at")
    )
    for order in orders:
        any_allocated_for_order = False
        now = datetime.now(timezone.utc)
        for item in order.items.select_related("product__product_card").filter(
            product=product
        ):
            qty = int(item.quantity)
            already = int(item.reserved_digital_items.count())
            need = max(qty - already, 0)
            if need <= 0:
                continue
            available = list(
                DigitalItem.objects.select_for_update()
                .filter(product_id=product.id, is_used=False, reserved_at__isnull=True)
                .order_by("id")[:need]
            )
            take = min(len(available), need)
            if take <= 0:
                continue
            available = available[:take]
            for di in available:
                di.is_used = True
                di.used_at = now
            DigitalItem.objects.bulk_update(
                available, ["is_used", "used_at", "updated_at"]
            )
            OrderItemDigitalItem.objects.bulk_create(
                [
                    OrderItemDigitalItem(order_item=item, digital_item=di)
                    for di in available
                ]
            )
            any_allocated_for_order = True

        instant_items = list(
            order.items.select_related("product__product_card").filter(
                product__product_card__fulfillment_mode=ProductCard.FulfillmentMode.INSTANT
            )
        )
        all_instant_fulfilled = all(
            int(instant_item.reserved_digital_items.count())
            >= int(instant_item.quantity)
            for instant_item in instant_items
        )

        if not all_instant_fulfilled:
            if (
                any_allocated_for_order
                or order.status == Order.Status.PARTIALLY_FULFILLED
            ):
                transition_order_status(
                    order,
                    Order.Status.PARTIALLY_FULFILLED,
                    actor="orders",
                    note="Partially delivered, waiting for remaining stock.",
                )
            else:
                transition_order_status(
                    order,
                    Order.Status.WAITING_STOCK,
                    actor="orders",
                    note="Paid, waiting for stock to deliver instant items.",
                )
            continue

        has_manual_items = order.items.filter(
            product__product_card__fulfillment_mode=ProductCard.FulfillmentMode.MANUAL
        ).exists()
        if has_manual_items:
            if not order.manual_dispatches.exists():
                dispatch_manual_order(order)
            transition_order_status(
                order,
                Order.Status.MANUAL_PENDING,
                actor="orders",
                note="Instant items fulfilled, manual fulfillment required.",
            )
        else:
            transition_order_status(
                order,
                Order.Status.COMPLETED,
                actor="orders",
                note="Stock arrived; order delivered.",
            )
            transaction.on_commit(
                lambda order=order: notify_telegram_bot_new_order(order)
            )
            _queue_order_completed_email(order)
            fulfilled_preorder_ids = list(
                PreOrder.objects.filter(
                    order=order, status=PreOrder.Status.PAID
                ).values_list("public_id", flat=True)
            )
            PreOrder.objects.filter(order=order, status=PreOrder.Status.PAID).update(
                status=PreOrder.Status.FULFILLED,
                fulfilled_at=django_timezone.now(),
            )
            for preorder_public_id in fulfilled_preorder_ids:
                transaction.on_commit(
                    lambda order=order,
                    preorder_public_id=preorder_public_id: notify_telegram_bot_preorder_fulfilled(
                        order, int(preorder_public_id)
                    )
                )
            completed += 1

    product.stock_count = DigitalItem.objects.filter(
        product_id=product.id,
        is_used=False,
        reserved_at__isnull=True,
    ).count()
    product.save(update_fields=["stock_count", "updated_at"])
    return completed


def _build_manual_payload(order: Order) -> dict:
    """
    Manual order notification must match the regular /orders/notify payload,
    just delivered to a different TG topic.
    """
    payload = _build_order_notify_payload(order)
    # Keep the legacy fields for compatibility with existing dispatch logs.
    payload["created_at"] = order.created_at.isoformat()
    payload["guest_email"] = (order.guest_email or "").strip()
    return payload


def dispatch_manual_order(order: Order) -> ManualDispatchLog:
    payload = _build_manual_payload(order)
    tg_log = _create_tg_notify_log(
        order=order, kind=OrderTelegramNotifyLog.Kind.MANUAL_ORDER, payload=payload
    )
    log = ManualDispatchLog.objects.create(
        order=order,
        status=ManualDispatchLog.DispatchStatus.QUEUED,
        chat_id="",
        message_id="",
        payload_snapshot=payload,
    )
    transaction.on_commit(lambda log_id=log.id, tg_log_id=tg_log.id: _send_manual_dispatch(log_id, tg_log_id))
    return log


def _send_manual_dispatch(dispatch_log_id: int, tg_log_id: int | None = None) -> None:
    """
    Network side-effect; must run outside of DB transaction.
    """
    try:
        log = ManualDispatchLog.objects.select_related("order").get(id=dispatch_log_id)
    except ManualDispatchLog.DoesNotExist:
        return
    tg_log = None
    if tg_log_id:
        tg_log = OrderTelegramNotifyLog.objects.filter(id=tg_log_id).first()

    payload = dict(log.payload_snapshot or {})
    response = post_manual_order_notify(payload)
    if response and response.get("ok") is True:
        log.status = ManualDispatchLog.DispatchStatus.SENT
        log.chat_id = str(response.get("chat_id") or "")
        log.message_id = str(response.get("message_id") or "")
        log.sent_at = datetime.now(timezone.utc)
        log.error_message = ""
        log.save(
            update_fields=[
                "status",
                "chat_id",
                "message_id",
                "sent_at",
                "error_message",
                "updated_at",
            ]
        )
        if tg_log is not None:
            _mark_tg_notify_log_sent(tg_log, response=response)
        return

    log.status = ManualDispatchLog.DispatchStatus.FAILED
    log.error_message = "Manual dispatch failed"
    log.save(update_fields=["status", "error_message", "updated_at"])
    if tg_log is not None:
        _mark_tg_notify_log_failed(tg_log, "Manual dispatch failed")


def retry_order_telegram_notify(log: OrderTelegramNotifyLog) -> bool:
    """
    Manual/admin retry for failed/queued telegram notifications.
    """
    payload = dict(log.payload_snapshot or {})
    if log.kind == OrderTelegramNotifyLog.Kind.NEW_ORDER:
        ok = post_order_notify(payload)
    elif log.kind == OrderTelegramNotifyLog.Kind.PREORDER_PAID:
        resp = post_preorder_paid_notify(payload)
        ok = bool(resp and resp.get("ok") is True)
        if ok:
            _mark_tg_notify_log_sent(log, response=resp)
            return True
        _mark_tg_notify_log_failed(log, f"Retry failed for {log.kind}")
        return False
    elif log.kind == OrderTelegramNotifyLog.Kind.PREORDER_FULFILLED:
        ok = post_preorder_fulfilled_notify(payload)
    elif log.kind == OrderTelegramNotifyLog.Kind.MANUAL_ORDER:
        response = post_manual_order_notify(payload)
        ok = bool(response and response.get("ok") is True)
        if ok:
            _mark_tg_notify_log_sent(log, response=response)
            return True
    else:
        _mark_tg_notify_log_failed(log, f"Unknown TG notify kind: {log.kind}")
        return False

    if ok:
        _mark_tg_notify_log_sent(log)
        return True
    _mark_tg_notify_log_failed(log, f"Retry failed for {log.kind}")
    return False


def _telegram_notify_retry_delay_seconds(attempts_done: int) -> int:
    """
    Returns delay before next retry based on already done attempts.
    attempts_done=1 -> first retry delay, etc.
    """
    idx = max(int(attempts_done or 0) - 1, 0)
    if idx >= len(TELEGRAM_NOTIFY_RETRY_DELAYS_SECONDS):
        return int(TELEGRAM_NOTIFY_RETRY_DELAYS_SECONDS[-1])
    return int(TELEGRAM_NOTIFY_RETRY_DELAYS_SECONDS[idx])


def _telegram_notify_log_due_for_retry(log: OrderTelegramNotifyLog) -> bool:
    attempts = int(log.attempts or 0)
    max_attempts = int(log.max_attempts or 0)
    if attempts >= max_attempts:
        return False
    if log.last_attempt_at is None:
        return True
    delay_seconds = _telegram_notify_retry_delay_seconds(attempts_done=attempts)
    return log.last_attempt_at <= django_timezone.now() - timedelta(
        seconds=delay_seconds
    )


def retry_due_order_telegram_notifications(*, batch_limit: int = 200) -> tuple[int, int]:
    """
    Retries due telegram notifications in FAILED/QUEUED statuses.
    Returns (processed, succeeded).
    """
    limit = max(int(batch_limit or 0), 1)
    candidate_ids = list(
        OrderTelegramNotifyLog.objects.filter(
            Q(status=OrderTelegramNotifyLog.Status.FAILED)
            | Q(status=OrderTelegramNotifyLog.Status.QUEUED)
        )
        .order_by("last_attempt_at", "created_at")
        .values_list("id", flat=True)[:limit]
    )
    processed = 0
    succeeded = 0
    for log_id in candidate_ids:
        with transaction.atomic():
            log = (
                OrderTelegramNotifyLog.objects.select_for_update()
                .filter(id=log_id)
                .first()
            )
            if log is None:
                continue
            if log.status not in (
                OrderTelegramNotifyLog.Status.FAILED,
                OrderTelegramNotifyLog.Status.QUEUED,
            ):
                continue
            if not _telegram_notify_log_due_for_retry(log):
                continue
            ok = retry_order_telegram_notify(log)
            processed += 1
            if ok:
                succeeded += 1
    return processed, succeeded


def complete_manual_order(order: Order, *, actor: str = "admin") -> Order:
    if order.status != Order.Status.MANUAL_PENDING:
        return order
    transition_order_status(
        order,
        Order.Status.COMPLETED,
        actor=actor,
        note="Completed manually by operator.",
    )
    _queue_order_completed_email(order, is_manual_order=True)
    return order


def refresh_unique_buyers_count_for_cards(card_ids: list[int]) -> None:
    if not card_ids:
        return

    unique_counts = (
        Order.objects.filter(
            user__isnull=False,
            status__in=[
                Order.Status.PAID,
                Order.Status.MANUAL_PENDING,
                Order.Status.COMPLETED,
            ],
            items__product__product_card_id__in=card_ids,
        )
        .values("items__product__product_card_id")
        .annotate(unique_buyers=Count("user_id", distinct=True))
    )
    count_map = {
        row["items__product__product_card_id"]: row["unique_buyers"]
        for row in unique_counts
    }

    cards = ProductCard.objects.filter(id__in=card_ids)
    for card in cards:
        card.unique_buyers_count = int(count_map.get(card.id, 0))
    ProductCard.objects.bulk_update(cards, ["unique_buyers_count"])


@transaction.atomic
def process_paid_order(order: Order) -> Order:
    transition_order_status(
        order,
        Order.Status.PAID,
        actor="payments",
        note="Payment confirmed.",
    )

    # Keep explicit preorder model in sync (if exists).
    PreOrder.objects.filter(order=order, status=PreOrder.Status.PENDING).update(
        status=PreOrder.Status.PAID,
        paid_at=django_timezone.now(),
    )
    transaction.on_commit(lambda order=order: notify_telegram_bot_preorder_paid(order))

    reserved_links = list(
        OrderItemDigitalItem.objects.select_related(
            "digital_item", "order_item"
        ).filter(order_item__order=order)
    )
    if reserved_links:
        now = datetime.now(timezone.utc)
        items_to_update = []
        for link in reserved_links:
            item = link.digital_item
            if not item.is_used:
                item.is_used = True
                item.used_at = now
                items_to_update.append(item)
        if items_to_update:
            DigitalItem.objects.bulk_update(
                items_to_update, ["is_used", "used_at", "updated_at"]
            )
    else:
        # No reservations: allocate on payment time. If not enough stock, keep paid order waiting for stock.
        needs_stock = False
        any_instant_allocated = False
        now = datetime.now(timezone.utc)
        for item in order.items.select_related("product__product_card").all():
            if (
                item.product.product_card.fulfillment_mode
                != ProductCard.FulfillmentMode.INSTANT
            ):
                continue
            qty = int(item.quantity)
            available = list(
                DigitalItem.objects.select_for_update()
                .filter(
                    product_id=item.product_id,
                    is_used=False,
                    reserved_at__isnull=True,
                )
                .order_by("id")[:qty]
            )
            take = min(len(available), qty)
            if take <= 0:
                needs_stock = True
                continue
            if take < qty:
                needs_stock = True
            available = available[:take]
            for di in available:
                di.is_used = True
                di.used_at = now
            DigitalItem.objects.bulk_update(
                available, ["is_used", "used_at", "updated_at"]
            )
            OrderItemDigitalItem.objects.bulk_create(
                [
                    OrderItemDigitalItem(order_item=item, digital_item=di)
                    for di in available
                ]
            )
            any_instant_allocated = True
            item.product.stock_count = DigitalItem.objects.filter(
                product_id=item.product_id,
                is_used=False,
                reserved_at__isnull=True,
            ).count()
            item.product.save(update_fields=["stock_count", "updated_at"])

        if needs_stock:
            transition_order_status(
                order,
                (
                    Order.Status.PARTIALLY_FULFILLED
                    if any_instant_allocated
                    else Order.Status.WAITING_STOCK
                ),
                actor="orders",
                note=(
                    "Partially delivered, waiting for remaining stock."
                    if any_instant_allocated
                    else "Paid, waiting for stock to deliver instant items."
                ),
            )
            return order

    has_manual_items = order.items.filter(
        product__product_card__fulfillment_mode=ProductCard.FulfillmentMode.MANUAL
    ).exists()
    if has_manual_items:
        dispatch_manual_order(order)
        transition_order_status(
            order,
            Order.Status.MANUAL_PENDING,
            actor="orders",
            note="Manual fulfillment required.",
        )
    else:
        transition_order_status(
            order,
            Order.Status.COMPLETED,
            actor="orders",
            note="Instant order completed.",
        )
        transaction.on_commit(lambda order=order: notify_telegram_bot_new_order(order))
        _queue_order_completed_email(order)
        fulfilled_preorder_ids = list(
            PreOrder.objects.filter(
                order=order, status=PreOrder.Status.PAID
            ).values_list("public_id", flat=True)
        )
        PreOrder.objects.filter(order=order, status=PreOrder.Status.PAID).update(
            status=PreOrder.Status.FULFILLED,
            fulfilled_at=django_timezone.now(),
        )
        for preorder_public_id in fulfilled_preorder_ids:
            transaction.on_commit(
                lambda order=order,
                preorder_public_id=preorder_public_id: notify_telegram_bot_preorder_fulfilled(
                    order, int(preorder_public_id)
                )
            )
    touched_card_ids = list(
        order.items.values_list("product__product_card_id", flat=True).distinct()
    )
    refresh_unique_buyers_count_for_cards(touched_card_ids)
    return order


def _order_recipient_email(order: Order) -> str:
    if order.user_id and order.user and (order.user.email or "").strip():
        return (order.user.email or "").strip().lower()
    return (order.guest_email or "").strip().lower()


def _order_email_lines(order: Order) -> list[str]:
    rows: list[str] = []
    for item in (
        order.items.select_related("product__product_card")
        .prefetch_related("reserved_digital_items__digital_item")
        .all()
    ):
        header = f"{item.product.product_card.name} x{item.quantity} ({item.total_price} {order.currency})"
        payloads = [
            link.digital_item.payload_encrypted
            for link in item.reserved_digital_items.all()
        ]
        rows.append(header)
        if payloads:
            rows.extend(str(x) for x in payloads)
    return rows


def _queue_order_completed_email(order: Order, *, is_manual_order: bool = False) -> None:
    if order.status != Order.Status.COMPLETED:
        return
    recipient = _order_recipient_email(order)
    if not recipient:
        return
    dedup_key = f"order_completed_email:{order.public_id}"
    if not cache.add(dedup_key, 1, timeout=7 * 24 * 3600):
        return
    from django.conf import settings

    site = str(getattr(settings, "PUBLIC_SITE_URL", "http://127.0.0.1:8000")).rstrip(
        "/"
    )
    order_url = f"{site}/orders/{order.public_id}/"
    lines = _order_email_lines(order)
    try:
        try:
            from apps.notifications.tasks import send_order_completed_email_task
        except ModuleNotFoundError:
            send_order_completed_email_task = None

        if send_order_completed_email_task is not None:
            send_order_completed_email_task.apply_async(
                args=[
                    recipient,
                    int(order.public_id),
                    order_url,
                    lines,
                    bool(order.user_id is None),
                    bool(is_manual_order),
                ],
                queue=getattr(settings, "CELERY_EMAIL_QUEUE", "email"),
            )
            return
    except Exception:
        logger.exception("order_completed_email_queue_failed order_id={}", order.pk)

    try:
        from apps.notifications.mailing import send_order_completed_email

        send_order_completed_email(
            recipient=recipient,
            order_public_id=int(order.public_id),
            order_url=order_url,
            order_lines=lines,
            is_guest_order=bool(order.user_id is None),
            is_manual_order=bool(is_manual_order),
        )
    except Exception:
        logger.exception("order_completed_email_send_failed order_id={}", order.pk)


def reconcile_waiting_stock_orders(
    *, batch_limit_per_product: int = 100, max_products: int = 200
) -> int:
    """
    Best-effort stock reconciliation for all products that currently have waiting-stock orders.
    Useful as a safety net for flows where DigitalItem signals may not fire
    (e.g. bulk inserts, external imports).
    Returns number of orders that became COMPLETED.
    """
    product_ids = list(
        OrderItem.objects.filter(
            order__status__in=[
                Order.Status.WAITING_STOCK,
                Order.Status.PARTIALLY_FULFILLED,
            ]
        )
        .values_list("product_id", flat=True)
        .distinct()[:max_products]
    )
    if not product_ids:
        return 0

    products = list(
        Product.objects.filter(id__in=product_ids).select_related("product_card")
    )
    completed = 0
    for product in products:
        try:
            # Keep each product reconciliation isolated in its own transaction:
            # one broken product must not poison the whole batch.
            with transaction.atomic():
                completed += int(
                    fulfill_waiting_stock_orders_for_product(
                        product=product,
                        batch_limit=batch_limit_per_product,
                    )
                )
        except Exception:
            logger.exception("reconcile_waiting_stock_failed product_id={}", product.id)
    return completed


@transaction.atomic
def cancel_stale_unpaid_orders(
    *,
    order_ttl_hours: int = 24,
    reservation_ttl_minutes: int = 30,
    batch_limit: int = 500,
) -> int:
    now = django_timezone.now()
    order_cutoff = now - timedelta(hours=max(int(order_ttl_hours or 24), 1))
    reservation_cutoff = now - timedelta(
        minutes=max(int(reservation_ttl_minutes or 30), 1)
    )
    cancelled = 0
    stale_orders = list(
        Order.objects.select_for_update()
        .filter(
            status__in=[Order.Status.AWAITING_PAYMENT],
            created_at__lt=order_cutoff,
        )
        .order_by("created_at")[:batch_limit]
    )
    for order in stale_orders:
        links = list(
            OrderItemDigitalItem.objects.select_related("digital_item", "order_item")
            .filter(order_item__order=order)
            .order_by("id")
        )
        if links:
            releasable_links = [
                link
                for link in links
                if not link.digital_item.is_used
                and link.digital_item.reserved_at is not None
                and link.digital_item.reserved_at < reservation_cutoff
            ]
            if releasable_links:
                release_items = [link.digital_item for link in releasable_links]
                for digital_item in release_items:
                    digital_item.reserved_at = None
                DigitalItem.objects.bulk_update(
                    release_items, ["reserved_at", "updated_at"]
                )
                OrderItemDigitalItem.objects.filter(
                    id__in=[link.id for link in releasable_links]
                ).delete()
                touched_product_ids = {
                    link.order_item.product_id for link in releasable_links
                }
                for product_id in touched_product_ids:
                    Product.objects.filter(id=product_id).update(
                        stock_count=DigitalItem.objects.filter(
                            product_id=product_id,
                            is_used=False,
                            reserved_at__isnull=True,
                        ).count()
                    )

        transition_order_status(
            order,
            Order.Status.CANCELLED,
            actor="orders",
            note="Cancelled by unpaid order TTL.",
        )
        PreOrder.objects.filter(order=order, status=PreOrder.Status.PENDING).update(
            status=PreOrder.Status.CANCELLED,
            cancelled_at=django_timezone.now(),
        )
        cancelled += 1
    return cancelled


@transaction.atomic
def complete_stale_manual_pending_orders(
    *,
    ttl_hours: int = 48,
    batch_limit: int = 500,
) -> int:
    now = django_timezone.now()
    cutoff = now - timedelta(hours=max(int(ttl_hours or 48), 1))
    completed = 0
    stale_orders = list(
        Order.objects.select_for_update()
        .filter(status=Order.Status.MANUAL_PENDING, updated_at__lt=cutoff)
        .order_by("updated_at")[:batch_limit]
    )
    for order in stale_orders:
        if order.status != Order.Status.MANUAL_PENDING:
            continue
        transition_order_status(
            order,
            Order.Status.COMPLETED,
            actor="orders",
            note="Auto-completed by manual-pending TTL.",
        )
        _queue_order_completed_email(order, is_manual_order=True)
        completed += 1
    return completed
