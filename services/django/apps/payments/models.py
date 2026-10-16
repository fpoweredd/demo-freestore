from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.snowflake import generate_snowflake_id
from apps.orders.models import Order


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BalanceTopUp(TimeStampedModel):
    """User-initiated balance deposit (paid via external provider)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    public_id = models.BigIntegerField(
        unique=True, default=generate_snowflake_id, editable=False, db_index=True
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="balance_top_ups",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("user", "-created_at"), name="bal_topup_user_created_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"TopUp {self.public_id} ({self.amount} {self.currency})"


class PaymentProviderSettings(models.Model):
    """
    Enable/disable providers for checkout UI and balance top-up; per-provider top-up limits (RUB).
    API keys stay in environment / secrets — this model only controls availability and amounts.
    """

    provider_id = models.CharField(max_length=32, unique=True, db_index=True)
    is_enabled = models.BooleanField(
        default=False,
        help_text="If off, this provider is hidden in the balance page and rejects API top-up/init.",
    )
    balance_topup_min_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=10,
        help_text="Minimum balance top-up amount (RUB) for this provider.",
    )
    balance_topup_max_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=1_000_000,
        help_text="Maximum balance top-up amount (RUB) for this provider.",
    )
    show_on_product_page = models.BooleanField(
        default=True,
        help_text="If off, provider is hidden on product checkout and remains available only for balance top-up.",
    )
    product_min_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Hide provider on product page when selected product price is below this amount (RUB).",
    )
    ui_sort_order = models.PositiveIntegerField(
        default=100,
        help_text="Display order in payment buttons (lower values are shown first).",
    )

    class Meta:
        verbose_name = "Payment provider settings"
        verbose_name_plural = "Payment provider settings"

    def __str__(self) -> str:
        return f"{self.provider_id} (enabled={self.is_enabled})"

    def clean(self) -> None:
        from apps.payments.providers import PAYMENT_PROVIDERS

        pid = (self.provider_id or "").strip().lower()
        if not pid:
            raise ValidationError({"provider_id": "Provider id is required."})
        if pid not in PAYMENT_PROVIDERS:
            raise ValidationError(
                {
                    "provider_id": "This provider is not registered in code (add provider class first)."
                }
            )
        if self.balance_topup_min_amount > self.balance_topup_max_amount:
            raise ValidationError(
                {"balance_topup_min_amount": "Min must be less than or equal to max."}
            )
        if self.product_min_amount < Decimal("0"):
            raise ValidationError(
                {"product_min_amount": "Value must be greater than or equal to 0."}
            )

    def save(self, *args, **kwargs):
        self.provider_id = (self.provider_id or "").strip().lower()
        self.full_clean()
        super().save(*args, **kwargs)


class Payment(TimeStampedModel):
    """
    One row per payment attempt. Either linked to an Order (checkout) or BalanceTopUp (deposit).
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"  # local only, before provider ack
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"
        REFUNDED = "refunded", "Refunded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="payments",
        null=True,
        blank=True,
    )
    balance_top_up = models.ForeignKey(
        BalanceTopUp,
        on_delete=models.CASCADE,
        related_name="payments",
        null=True,
        blank=True,
    )
    provider = models.CharField(max_length=32, db_index=True)
    provider_payment_id = models.CharField(
        max_length=128,
        unique=True,
        null=True,
        blank=True,
        help_text="Provider payment id; may be set after invoice or first IPN.",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    provider_status = models.CharField(max_length=64, blank=True)
    idempotency_key = models.CharField(max_length=64, blank=True, db_index=True)
    invoice_url = models.URLField(blank=True, max_length=2048)
    webhook_received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(order__isnull=False, balance_top_up__isnull=True)
                    | models.Q(order__isnull=True, balance_top_up__isnull=False)
                ),
                name="payment_order_xor_balance_top_up",
            ),
        ]
        indexes = [
            models.Index(
                fields=("order", "-created_at"), name="payment_order_created_idx"
            ),
            models.Index(
                fields=("balance_top_up", "-created_at"),
                name="payment_bal_topup_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Payment {self.pk} ({self.provider})"


class PaymentWebhookLog(TimeStampedModel):
    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="webhook_logs",
        null=True,
        blank=True,
    )
    raw_payload = models.JSONField(default=dict)
    signature_valid = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)


class WalletTransaction(TimeStampedModel):
    class Kind(models.TextChoices):
        TOPUP_CREDIT = "topup_credit", "Top-up credit"
        ORDER_DEBIT = "order_debit", "Order debit"
        REFUND_CREDIT = "refund_credit", "Refund credit"
        CHARGEBACK_DEBIT = "chargeback_debit", "Chargeback debit"
        MANUAL_ADJUSTMENT = "manual_adjustment", "Manual adjustment"

    class SourceType(models.TextChoices):
        PAYMENT = "payment", "Payment"
        REFUND = "refund", "Refund"
        ORDER = "order", "Order"
        MANUAL = "manual", "Manual"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet_transactions",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    source_type = models.CharField(max_length=32, choices=SourceType.choices)
    source_id = models.CharField(max_length=64)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Signed amount. Positive = credit, negative = debit.",
    )
    currency = models.CharField(max_length=10, default="USD")
    balance_before = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    description = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("source_type", "source_id", "kind"),
                name="wallet_tx_unique_source_kind",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "-created_at"), name="wallet_tx_user_created_idx"
            ),
            models.Index(fields=("kind",), name="wallet_tx_kind_idx"),
        ]

    def __str__(self) -> str:
        return f"Wallet tx {self.kind} {self.amount} for user {self.user_id}"

    def clean(self) -> None:
        if self.amount == Decimal("0"):
            raise ValidationError({"amount": "Amount cannot be zero."})


class PaymentRefund(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="refunds",
    )
    provider_refund_id = models.CharField(max_length=128, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    reason = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("payment", "provider_refund_id"),
                name="payment_refund_unique_provider_refund_id",
                condition=~models.Q(provider_refund_id=""),
            ),
        ]

    def __str__(self) -> str:
        return f"Refund {self.payment_id} {self.amount} {self.currency}"
