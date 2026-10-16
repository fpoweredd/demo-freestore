from decimal import Decimal
import secrets
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import AccountProfile
from apps.catalog.models import Product, ProductInputField
from apps.catalog.sku_display import build_selected_sku_rows
from apps.core.services import get_shop_settings
from apps.payments.internal_balance import INTERNAL_BALANCE_PROVIDER_ID
from apps.payments.providers.registry import (
    get_product_provider_buttons,
    is_stub_provider,
)
from apps.payments.services import (
    init_payment_for_order,
    reconcile_order_payment_on_return,
)

from .models import ManualDispatchLog, Order, OrderStatusLog, PreOrder
from .serializers import (
    ManualDispatchLogSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    QuoteRequestSerializer,
)
from .services import (
    build_checkout_quote,
    create_order_from_quote,
    process_paid_order,
    reconcile_waiting_stock_orders,
)

GUEST_ORDER_SESSION_KEY = "guest_order_public_ids"
TELEGRAM_HANDLE_INPUT_KEY = "telegram_handle"
TELEGRAM_HANDLE_INPUT_LABEL = "Telegram"


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _guest_order_ids_from_session(request) -> set[int]:
    raw = request.session.get(GUEST_ORDER_SESSION_KEY) or []
    result: set[int] = set()
    for value in raw:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _store_guest_order_in_session(request, public_id: int) -> None:
    ids = _guest_order_ids_from_session(request)
    ids.add(int(public_id))
    request.session[GUEST_ORDER_SESSION_KEY] = sorted(ids)[-100:]
    request.session.modified = True


def _session_utm_params(request) -> dict[str, str]:
    raw = request.session.get("utm_params") or {}
    if not isinstance(raw, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in raw.items():
        k = str(key or "").strip()
        v = str(value or "").strip()
        if k and v:
            result[k] = v
    return result


def _resolve_order_for_page(request, public_id: int) -> Order:
    qs = (
        Order.objects.select_related("preorder")
        .prefetch_related(
            "items__product__product_card",
            "items__reserved_digital_items__digital_item",
            "status_logs",
        )
        .order_by("-created_at")
    )
    order = qs.filter(public_id=public_id).first()
    if not order:
        raise Http404("Order not found.")
    if request.user.is_authenticated:
        if order.user_id != request.user.id:
            raise Http404("Order not found.")
        return order
    if order.user_id is not None:
        raise Http404("Order not found.")
    if int(order.public_id) not in _guest_order_ids_from_session(request):
        raise Http404("Order not found.")
    return order


def _insufficient_balance_response(request, *, product_slug: str, shortfall: str = ""):
    topup_url = reverse("accounts:balance")
    redirect_url = reverse("catalog:product-detail", kwargs={"slug": product_slug})
    if _is_htmx(request):
        response = HttpResponse("ok")
        response["HX-Reswap"] = "none"
        response["X-Insufficient-Balance"] = "1"
        response["X-Balance-Topup-Url"] = topup_url
        response["X-Insufficient-Balance-Shortfall"] = str(shortfall or "")
        return response
    message_text = "Insufficient balance"
    if shortfall:
        message_text = f"Insufficient balance. You need {shortfall} more USD."
    messages.error(request, message_text)
    return redirect(redirect_url)


def _build_order_page_context(order: Order) -> dict:
    latest_payment = order.payments.order_by("-created_at").first()
    order_item_views: list[dict] = []
    purchased_content_lines: list[str] = []
    product_card_ids: set[int] = set()
    for item in (
        order.items.select_related("product__product_card")
        .prefetch_related("reserved_digital_items__digital_item")
        .all()
    ):
        product_card_ids.add(int(item.product.product_card_id))
        item_payloads = [
            link.digital_item.payload_encrypted
            for link in item.reserved_digital_items.all()
        ]
        purchased_content_lines.extend(item_payloads)
        order_item_views.append(
            {
                "item": item,
                "item_payloads": item_payloads,
                "selection_rows": build_selected_sku_rows(
                    product_id=item.product_id,
                    price=item.unit_price,
                    attributes=item.product.attributes or {},
                    selector_axes=item.product.product_card.selector_axes or [],
                    ui_labels=item.product.product_card.ui_labels or {},
                ),
            }
        )

    input_fields_by_card: dict[int, list[ProductInputField]] = {}
    if product_card_ids:
        qs = (
            ProductInputField.objects.filter(
                product_card_id__in=product_card_ids, is_active=True
            )
            .only("product_card_id", "key", "label", "field_type", "sort_order")
            .order_by("product_card_id", "sort_order", "id")
        )
        for field in qs:
            input_fields_by_card.setdefault(int(field.product_card_id), []).append(
                field
            )

    for row in order_item_views:
        item = row["item"]
        payload = item.input_payload or {}
        card_id = int(item.product.product_card_id)
        fields = input_fields_by_card.get(card_id, [])

        labeled_rows: list[dict] = []
        used_keys: set[str] = set()
        for field in fields:
            key = str(field.key)
            if key not in payload:
                continue
            value = str(payload.get(key) or "").strip()
            if not value:
                continue
            labeled_rows.append(
                {
                    "key": key,
                    "label": str(field.label or key),
                    "value": value,
                    "is_password": field.field_type
                    == ProductInputField.FieldType.PASSWORD
                    or "password" in key.lower(),
                }
            )
            used_keys.add(key)

        # If payload contains unknown keys (e.g. legacy), show them too.
        if isinstance(payload, dict):
            for key in sorted(payload.keys()):
                if key in used_keys:
                    continue
                value = str(payload.get(key) or "").strip()
                if not value:
                    continue
                labeled_rows.append(
                    {
                        "key": str(key),
                        "label": (
                            TELEGRAM_HANDLE_INPUT_LABEL
                            if str(key) == TELEGRAM_HANDLE_INPUT_KEY
                            else str(key)
                        ),
                        "value": value,
                        "is_password": "password" in str(key).lower(),
                    }
                )

        row["input_rows"] = labeled_rows
    return {
        "order": order,
        "order_item_views": order_item_views,
        "purchased_content_text": "\n".join(purchased_content_lines),
        "show_content_actions": order.status == Order.Status.COMPLETED
        and bool(purchased_content_lines),
        "latest_payment": latest_payment,
        "terminal_statuses": [
            Order.Status.COMPLETED,
            Order.Status.CANCELLED,
            Order.Status.MANUAL_PENDING,
        ],
    }


def _flatten_checkout_validation_error(
    exc: DjangoValidationError,
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    error_dict = getattr(exc, "error_dict", None)
    if error_dict:
        for field, msg_list in error_dict.items():
            out[str(field)] = [str(m) for m in msg_list]
        return out
    for m in getattr(exc, "messages", []):
        out.setdefault("__all__", []).append(str(m))
    if not out:
        out["__all__"] = [str(exc)]
    return out


def _checkout_validation_summary_lines(errs: dict[str, list[str]]) -> list[str]:
    priority = ("guest_email", "quantity", "product_id")
    seen: set[str] = set()
    lines: list[str] = []
    for k in priority:
        if k not in errs:
            continue
        for s in errs[k]:
            text = (str(s) or "").strip()
            if text:
                lines.append(text)
        seen.add(k)
    for key, msgs in errs.items():
        if key in seen:
            continue
        for s in msgs:
            text = (str(s) or "").strip()
            if text:
                lines.append(text)
    return lines


def _product_checkout_validation_response(
    request, exc: DjangoValidationError, *, product_slug: str
) -> HttpResponse:
    errors = _flatten_checkout_validation_error(exc)
    summary_lines = _checkout_validation_summary_lines(errors)
    summary = (
        " ".join(summary_lines[:4])
        if summary_lines
        else "Could not place the order. Check your details."
    )
    if _is_htmx(request):
        return JsonResponse({"errors": errors, "summary": summary}, status=422)
    messages.error(request, summary)
    return redirect(
        reverse("catalog:product-detail", kwargs={"slug": product_slug})
    )


def order_create_from_product_view(request):
    if request.method != "POST":
        return redirect("catalog:home")
    try:
        if not get_shop_settings().buy_enabled:
            message_text = "Purchases are temporarily disabled."
            if _is_htmx(request):
                response = HttpResponse("ok")
                response["HX-Reswap"] = "none"
                messages.error(request, message_text)
                return response
            messages.error(request, message_text)
            return redirect("catalog:home")
    except Exception:
        pass

    product_id = request.POST.get("product_id")
    try:
        from apps.catalog.visibility import purchasable_products

        product = purchasable_products().select_related("product_card").get(
            id=product_id,
        )
    except Product.DoesNotExist:
        messages.error(request, "Product is not available.")
        return redirect("catalog:home")

    qty_raw = request.POST.get("quantity") or "1"
    try:
        quantity = max(int(qty_raw), 1)
    except (TypeError, ValueError):
        quantity = 1

    inputs: dict[str, str] = {}
    for key, value in request.POST.items():
        if not key.startswith("input__"):
            continue
        field_key = key.replace("input__", "", 1).strip()
        if not field_key:
            continue
        inputs[field_key] = (value or "").strip()

    guest_email = (request.POST.get("guest_email") or "").strip()
    user = request.user if request.user.is_authenticated else None
    if user and user.email and not guest_email:
        guest_email = user.email

    provider = (
        (request.POST.get("provider") or INTERNAL_BALANCE_PROVIDER_ID).strip().lower()
    )
    allowed_provider_ids = {INTERNAL_BALANCE_PROVIDER_ID}
    allowed_provider_ids.update({row["id"] for row in get_product_provider_buttons()})
    if provider not in allowed_provider_ids:
        provider = INTERNAL_BALANCE_PROVIDER_ID

    if is_stub_provider(provider):
        messages.error(
            request,
            "This payment method is coming soon. Please choose another.",
        )
        redirect_url = reverse(
            "catalog:product-detail", kwargs={"slug": product.product_card.slug}
        )
        if _is_htmx(request):
            response = HttpResponse("")
            response["HX-Redirect"] = redirect_url
            return response
        return redirect(redirect_url)

    if provider == INTERNAL_BALANCE_PROVIDER_ID:
        if user is None:
            if _is_htmx(request):
                response = HttpResponse("ok")
                response["HX-Reswap"] = "none"
                response["X-Open-Auth-Modal"] = "1"
                response["X-Open-Auth-Modal-Url"] = (
                    reverse("accounts:auth-modal-login")
                    + "?hint=balance_requires_login"
                )
                return response
            messages.error(
                request, "Sign in to pay with your balance."
            )
            return redirect(
                reverse(
                    "catalog:product-detail", kwargs={"slug": product.product_card.slug}
                )
            )

    idem_key = (request.POST.get("idempotency_key") or "").strip()
    if not idem_key:
        # Each new buy click should create a new order by default.
        # True idempotency must come from an explicit client-provided key.
        idem_key = f"pd-{product.id}-{uuid4().hex}"

    try:
        if provider == INTERNAL_BALANCE_PROVIDER_ID:
            quote = build_checkout_quote(
                items_data=[
                    {"product_id": product.id, "quantity": quantity, "inputs": inputs}
                ],
                currency="USD",
                user=user,
            )
            checkout_ctx = quote.get("checkout", {}) or {}
            if not bool(checkout_ctx.get("wallet_can_pay")):
                profile, _ = AccountProfile.objects.get_or_create(user=user)
                total = Decimal(str(quote.get("total") or "0"))
                balance = Decimal(str(profile.balance or Decimal("0.00")))
                shortfall = total - balance
                return _insufficient_balance_response(
                    request,
                    product_slug=product.product_card.slug,
                    shortfall=str(shortfall if shortfall > 0 else Decimal("0.00")),
                )

        order = create_order_from_quote(
            items_data=[
                {"product_id": product.id, "quantity": quantity, "inputs": inputs}
            ],
            guest_email=guest_email,
            currency="USD",
            user=user,
            idempotency_key=idem_key[:64],
            utm_params=_session_utm_params(request),
        )
    except DjangoValidationError as exc:
        return _product_checkout_validation_response(
            request,
            exc,
            product_slug=product.product_card.slug,
        )

    if order.user_id is None:
        _store_guest_order_in_session(request, int(order.public_id))
    payment = None
    if order.status == Order.Status.AWAITING_PAYMENT:
        try:
            payment = init_payment_for_order(
                order_public_id=order.public_id,
                provider_name=provider,
                user=user,
                guest_email=guest_email,
            )
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Payment init failed: {exc}")

    redirect_url = reverse(
        "orders-web:order-page", kwargs={"public_id": order.public_id}
    )
    if (
        payment is not None
        and provider != INTERNAL_BALANCE_PROVIDER_ID
        and getattr(payment, "invoice_url", "")
    ):
        redirect_url = payment.invoice_url
    if _is_htmx(request):
        response = HttpResponse("")
        response["HX-Redirect"] = redirect_url
        return response
    return redirect(redirect_url)


def order_page_view(request, public_id: int):
    try:
        reconcile_order_payment_on_return(
            order_public_id=public_id,
            query_params={k: v for k, v in request.GET.items()},
        )
    except Exception:  # noqa: BLE001
        pass
    order = _resolve_order_for_page(request, public_id=public_id)
    if order.status in (
        Order.Status.WAITING_STOCK,
        Order.Status.PARTIALLY_FULFILLED,
    ):
        try:
            throttle_key = f"reconcile_waiting_stock:view:{order.public_id}"
            if cache.add(throttle_key, 1, timeout=10):
                reconcile_waiting_stock_orders()
            order = _resolve_order_for_page(request, public_id=public_id)
        except Exception:
            pass
    context = _build_order_page_context(order)
    context["is_htmx"] = _is_htmx(request)
    if _is_htmx(request):
        return render(request, "orders/partials/order_page_content.html", context)
    return render(request, "orders/order_page.html", context)


def order_status_partial_view(request, public_id: int):
    order = _resolve_order_for_page(request, public_id=public_id)
    response = render(
        request,
        "orders/partials/order_status_card.html",
        _build_order_page_context(order),
    )
    if order.status in (
        Order.Status.COMPLETED,
        Order.Status.CANCELLED,
        Order.Status.MANUAL_PENDING,
    ):
        response["HX-Trigger"] = "order-content-refresh"
    return response


def order_payment_partial_view(request, public_id: int):
    order = _resolve_order_for_page(request, public_id=public_id)
    return render(
        request,
        "orders/partials/order_payment_box.html",
        _build_order_page_context(order),
    )


class OrderQuoteAPIView(APIView):
    def post(self, request):
        serializer = QuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        quote = build_checkout_quote(
            items_data=data["items"],
            currency=data["currency"],
            user=request.user if request.user.is_authenticated else None,
        )
        return Response(quote)


class OrderViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [permissions.AllowAny]
    serializer_class = OrderSerializer
    queryset = Order.objects.prefetch_related(
        "items__reserved_digital_items", "status_logs"
    ).order_by("-created_at")
    lookup_field = "public_id"

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_authenticated:
            return queryset.filter(user=self.request.user)
        public_id = self.kwargs.get("public_id")
        if public_id is not None:
            return queryset.filter(public_id=public_id, user__isnull=True)
        return queryset.none()

    def create(self, request, *args, **kwargs):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user if request.user.is_authenticated else None
        order = create_order_from_quote(
            items_data=serializer.validated_data["items"],
            guest_email=serializer.validated_data.get("guest_email", ""),
            currency=serializer.validated_data["currency"],
            user=user,
            idempotency_key=serializer.validated_data.get("idempotency_key", ""),
            utm_params=_session_utm_params(request),
        )
        output = self.get_serializer(order)
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(methods=["post"], detail=True, url_path="pay-simulate")
    def pay_simulate(self, request, public_id=None):
        if not settings.DEBUG:
            return Response(status=status.HTTP_404_NOT_FOUND)
        order = self.get_object()
        process_paid_order(order)
        return Response(self.get_serializer(order).data)


class ManualDispatchLogViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = ManualDispatchLogSerializer
    queryset = ManualDispatchLog.objects.select_related("order").order_by("-created_at")

    def get_queryset(self):
        queryset = super().get_queryset()
        order_public_id = self.request.query_params.get("order_public_id")
        if not order_public_id:
            return ManualDispatchLog.objects.none()
        order = get_object_or_404(Order, public_id=order_public_id)
        return queryset.filter(order=order)


class PreOrderStockUploadRequestAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, public_id: int):
        expected_key = str(getattr(settings, "BOT_INTERNAL_API_KEY", "") or "").strip()
        incoming_key = str(request.headers.get("x-api-key") or "").strip()
        if not expected_key:
            return Response(
                {"detail": "Invalid API key"}, status=status.HTTP_401_UNAUTHORIZED
            )
        try:
            key_ok = secrets.compare_digest(incoming_key, expected_key)
        except (TypeError, ValueError):
            key_ok = False
        if not key_ok:
            return Response(
                {"detail": "Invalid API key"}, status=status.HTTP_401_UNAUTHORIZED
            )

        preorder = get_object_or_404(
            PreOrder.objects.select_related(
                "order", "product", "product__product_card"
            ),
            public_id=public_id,
        )
        product = preorder.product
        required_qty_total = (
            PreOrder.objects.filter(product=product, status=PreOrder.Status.PAID)
            .aggregate(total_qty=Sum("quantity"))
            .get("total_qty")
            or 0
        )
        base = str(
            getattr(settings, "PUBLIC_SITE_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        admin_url = (
            f"{base}{reverse('admin:catalog_digitalitem_bulk_upload')}"
            f"?product_id={product.id}"
        )

        if preorder.order_id:
            OrderStatusLog.objects.create(
                order=preorder.order,
                from_status=preorder.order.status,
                to_status=preorder.order.status,
                actor="telegram_bot",
                note="Operator requested stock upload link from Telegram preorder workflow.",
            )

        return Response(
            {
                "ok": True,
                "preorder_public_id": int(preorder.public_id),
                "product_id": int(product.id),
                "product_name": product.product_card.name,
                "required_qty_total": int(required_qty_total),
                "admin_url": admin_url,
            }
        )
