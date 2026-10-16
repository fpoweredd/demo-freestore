from decimal import Decimal

from rest_framework import serializers

from .internal_balance import INTERNAL_BALANCE_PROVIDER_ID
from .models import Payment, WalletTransaction
from .providers import PAYMENT_PROVIDERS


class PaymentInitSerializer(serializers.Serializer):
    order_public_id = serializers.IntegerField(min_value=1)
    provider = serializers.CharField(default="nowpayments", max_length=32)
    guest_email = serializers.EmailField(required=False, allow_blank=True)

    def validate_provider(self, value: str) -> str:
        key = (value or "").strip().lower()
        if key not in PAYMENT_PROVIDERS and key != INTERNAL_BALANCE_PROVIDER_ID:
            raise serializers.ValidationError("Unsupported provider.")
        return key


class BalanceTopupInitSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    currency = serializers.CharField(default="USD", max_length=10)
    provider = serializers.CharField(default="nowpayments", max_length=32)

    def validate_provider(self, value: str) -> str:
        key = (value or "").strip().lower()
        if key not in PAYMENT_PROVIDERS:
            raise serializers.ValidationError("Unsupported provider.")
        return key


class PaymentSerializer(serializers.ModelSerializer):
    order_public_id = serializers.SerializerMethodField()
    balance_top_up_public_id = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = (
            "id",
            "order_public_id",
            "balance_top_up_public_id",
            "provider",
            "provider_payment_id",
            "amount",
            "currency",
            "status",
            "provider_status",
            "invoice_url",
            "created_at",
        )

    def get_order_public_id(self, obj: Payment):
        return obj.order.public_id if obj.order_id else None

    def get_balance_top_up_public_id(self, obj: Payment):
        return obj.balance_top_up.public_id if obj.balance_top_up_id else None


class WalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletTransaction
        fields = (
            "id",
            "kind",
            "amount",
            "currency",
            "balance_before",
            "balance_after",
            "description",
            "metadata",
            "created_at",
        )
