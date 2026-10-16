"""HTTP callbacks from services/telegram-bot into Django (CSRF-exempt, API key)."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import Order
from .services import complete_manual_order


def _manual_complete_token_valid(*, order_public_id: int, token: str) -> bool:
    secret = (getattr(settings, "BOT_INTERNAL_API_KEY", "") or "").strip().encode("utf-8")
    if not secret:
        return False
    expected = hmac.new(
        secret,
        str(int(order_public_id)).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()[:12]
    return hmac.compare_digest(expected, (token or "").strip().lower())


@method_decorator(csrf_exempt, name="dispatch")
class ManualOrderTelegramCompleteView(View):
    def post(self, request, *args, **kwargs):
        expected_key = (getattr(settings, "BOT_INTERNAL_API_KEY", "") or "").strip()
        incoming_key = (request.headers.get("x-api-key") or "").strip()
        if not expected_key:
            return JsonResponse({"detail": "Invalid API key"}, status=401)
        try:
            key_ok = secrets.compare_digest(incoming_key, expected_key)
        except (TypeError, ValueError):
            key_ok = False
        if not key_ok:
            return JsonResponse({"detail": "Invalid API key"}, status=401)

        try:
            body = json.loads(request.body.decode() or "{}")
        except Exception:
            return JsonResponse({"detail": "Invalid JSON"}, status=400)

        try:
            order_public_id = int(body.get("order_public_id"))
        except Exception:
            return JsonResponse({"detail": "order_public_id is required"}, status=400)

        token = str(body.get("callback_token") or "")
        if not _manual_complete_token_valid(order_public_id=order_public_id, token=token):
            return JsonResponse({"detail": "Invalid callback token"}, status=403)

        with transaction.atomic():
            try:
                order = Order.objects.select_for_update().get(public_id=order_public_id)
            except Order.DoesNotExist:
                return JsonResponse({"detail": "Order not found"}, status=404)

            if order.status != Order.Status.MANUAL_PENDING:
                if order.status == Order.Status.COMPLETED:
                    return JsonResponse({"ok": True, "already_completed": True})
                return JsonResponse(
                    {
                        "detail": f"Order status is {order.status}, "
                        "expected manual_pending.",
                    },
                    status=409,
                )

            complete_manual_order(order, actor="telegram:manual_complete")

        return JsonResponse({"ok": True})
