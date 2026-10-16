from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.bot_api_client import post_payment_error_notify

from .serializers import (
    BalanceTopupInitSerializer,
    PaymentInitSerializer,
    PaymentSerializer,
    WalletTransactionSerializer,
)
from .services import (
    apply_enot_webhook,
    apply_nowpayments_webhook,
    apply_rollypay_webhook,
    init_balance_topup_payment,
    init_payment_for_order,
)

from .internal_balance import get_wallet_transactions
from .providers.enot import EnotProvider
from .providers.nowpayments import NowPaymentsProvider
from .providers.rollypay import RollyPayProvider


class WalletTransactionsAPIView(APIView):
    """GET /api/v1/payments/wallet/transactions/ — authenticated wallet history."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        entries = get_wallet_transactions(user_id=request.user.pk)
        return Response(
            {
                "entries": WalletTransactionSerializer(entries, many=True).data,
            }
        )


class PaymentInitAPIView(APIView):
    """POST /api/v1/payments/init/ — create provider invoice for an awaiting order."""

    permission_classes = [AllowAny]

    def post(self, request):
        ser = PaymentInitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            payment = init_payment_for_order(
                order_public_id=data["order_public_id"],
                provider_name=data["provider"],
                user=request.user if request.user.is_authenticated else None,
                guest_email=data.get("guest_email") or "",
            )
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class BalanceTopupInitAPIView(APIView):
    """POST /api/v1/payments/balance-topup/init/ — invoice for account balance (auth only)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = BalanceTopupInitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            payment = init_balance_topup_payment(
                user=request.user,
                amount=data["amount"],
                currency=data.get("currency") or "USD",
                provider_name=data["provider"],
            )
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


@method_decorator(csrf_exempt, name="dispatch")
class NowPaymentsWebhookAPIView(APIView):
    """POST /webhooks/nowpayments/ — provider IPN (no CSRF, signature-checked)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        raw = request.body
        sig = request.headers.get("x-nowpayments-sig") or request.META.get("HTTP_X_NOWPAYMENTS_SIG")
        prov = NowPaymentsProvider()
        ok, payload = prov.verify_webhook(raw_body=raw, signature_header=sig)
        valid = bool(ok and payload is not None)
        if not valid:
            post_payment_error_notify(
                {
                    "provider_id": "nowpayments",
                    "error_code": "webhook_signature_invalid",
                    "error_message": "Webhook signature validation failed.",
                    "context": {
                        "has_signature_header": str(bool(sig)),
                        "payload_size": str(len(raw or b"")),
                    },
                }
            )
        code, _ = apply_nowpayments_webhook(
            payload=payload if valid else {},
            signature_valid=valid,
        )
        return Response({"ok": code < 400}, status=code)


@method_decorator(csrf_exempt, name="dispatch")
class RollyPayWebhookAPIView(APIView):
    """POST /webhooks/rollypay/ — RollyPay webhooks (X-Signature + X-Timestamp, raw body)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        raw = request.body
        sig = request.headers.get("X-Signature") or request.META.get("HTTP_X_SIGNATURE")
        ts = request.headers.get("X-Timestamp") or request.META.get("HTTP_X_TIMESTAMP")
        prov = RollyPayProvider()
        ok, payload = prov.verify_webhook(
            raw_body=raw, signature_header=sig, webhook_timestamp=ts
        )
        valid = bool(ok and payload is not None)
        if not valid:
            post_payment_error_notify(
                {
                    "provider_id": "rollypay",
                    "error_code": "webhook_signature_invalid",
                    "error_message": "Webhook signature validation failed.",
                    "context": {
                        "has_signature_header": str(bool(sig)),
                        "has_timestamp_header": str(bool(ts)),
                        "payload_size": str(len(raw or b"")),
                    },
                }
            )
        code, _ = apply_rollypay_webhook(
            payload=payload if valid else {},
            signature_valid=valid,
        )
        return Response({"ok": code < 400}, status=code)


@method_decorator(csrf_exempt, name="dispatch")
class EnotWebhookAPIView(APIView):
    """POST /webhooks/enot/ — Enot.io webhooks (x-api-sha256-signature, raw JSON body)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        raw = request.body
        sig = request.headers.get("x-api-sha256-signature") or request.META.get(
            "HTTP_X_API_SHA256_SIGNATURE"
        )
        prov = EnotProvider()
        ok, payload = prov.verify_webhook(raw_body=raw, signature_header=sig)
        valid = bool(ok and payload is not None)
        if not valid:
            post_payment_error_notify(
                {
                    "provider_id": "enot",
                    "error_code": "webhook_signature_invalid",
                    "error_message": "Webhook signature validation failed.",
                    "context": {
                        "has_signature_header": str(bool(sig)),
                        "payload_size": str(len(raw or b"")),
                    },
                }
            )
        code, _ = apply_enot_webhook(
            payload=payload if valid else {},
            signature_valid=valid,
        )
        return Response({"ok": code < 400}, status=code)
