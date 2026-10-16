from django.conf import settings
from django.db import models

from apps.catalog.models import DigitalItem, Product, ProductInputField
from apps.core.snowflake import generate_snowflake_id


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Order(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Processing"
        AWAITING_PAYMENT = "awaiting_payment", "Awaiting payment"
        PAID = "paid", "Paid"
        WAITING_STOCK = "waiting_stock", "Sent for processing"
        PARTIALLY_FULFILLED = "partially_fulfilled", "Partially fulfilled"
        MANUAL_PENDING = "manual_pending", "Sent for fulfillment"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    public_id = models.BigIntegerField(
        unique=True, default=generate_snowflake_id, editable=False
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    guest_email = models.EmailField(blank=True)
    checkout_idempotency_key = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        unique=True,
        help_text="Client-supplied key to make checkout order creation idempotent.",
    )
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.PENDING
    )
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="USD")
    utm_params = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("public_id",), name="order_public_id_idx"),
            models.Index(fields=("status",), name="order_status_idx"),
            models.Index(
                fields=("checkout_idempotency_key",), name="order_checkout_idem_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"Order #{self.public_id}"


class OrderItem(TimeStampedModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="order_items"
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    input_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("id",)
        indexes = [
            models.Index(fields=("order",), name="orderitem_order_idx"),
            models.Index(fields=("product",), name="orderitem_product_idx"),
        ]

    def __str__(self) -> str:
        return f"OrderItem #{self.id} for order #{self.order_id}"


class OrderItemDigitalItem(TimeStampedModel):
    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.CASCADE,
        related_name="reserved_digital_items",
    )
    digital_item = models.OneToOneField(
        DigitalItem,
        on_delete=models.PROTECT,
        related_name="order_item_link",
    )

    class Meta:
        ordering = ("id",)
        constraints = [
            models.UniqueConstraint(
                fields=("order_item", "digital_item"),
                name="order_item_digital_item_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"OrderItemDigitalItem #{self.id} for order item #{self.order_item_id}"


class OrderStatusLog(TimeStampedModel):
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="status_logs"
    )
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30)
    actor = models.CharField(max_length=64, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=("order", "created_at"), name="ord_stlog_ord_created_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"Order #{self.order_id}: {self.from_status or '-'} -> {self.to_status}"


class PreOrder(TimeStampedModel):
    """
    Explicit preorder queue item.

    Created when instant stock is insufficient but preorders are enabled.
    Usually linked to an Order (created via checkout) and progresses with it.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"  # created, not paid yet (order awaiting payment)
        PAID = "paid", "Paid"  # payment succeeded, waiting for stock allocation
        FULFILLED = "fulfilled", "Fulfilled"  # stock allocated and order delivered
        CANCELLED = "cancelled", "Cancelled"

    public_id = models.BigIntegerField(
        unique=True, default=generate_snowflake_id, editable=False, db_index=True
    )
    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name="preorder",
        null=True,
        blank=True,
        help_text="Checkout-created order for this preorder (if any).",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="preorders",
    )
    guest_email = models.EmailField(blank=True)
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="preorders"
    )
    quantity = models.PositiveIntegerField(default=1)
    input_payload = models.JSONField(default=dict, blank=True)
    utm_params = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=("status", "created_at"), name="preord_stat_created_idx"
            ),
            models.Index(
                fields=("product", "status", "created_at"),
                name="preord_prod_stat_cr_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"PreOrder #{self.public_id} ({self.product_id})"


class OrderItemInput(TimeStampedModel):
    order_item = models.ForeignKey(
        OrderItem, on_delete=models.CASCADE, related_name="inputs"
    )
    input_field = models.ForeignKey(
        ProductInputField, on_delete=models.PROTECT, related_name="order_inputs"
    )
    value = models.TextField()

    class Meta:
        ordering = ("id",)
        constraints = [
            models.UniqueConstraint(
                fields=("order_item", "input_field"), name="order_item_input_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.input_field.key}={self.value}"


class ManualDispatchLog(TimeStampedModel):
    class DispatchStatus(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="manual_dispatches"
    )
    status = models.CharField(
        max_length=20, choices=DispatchStatus.choices, default=DispatchStatus.QUEUED
    )
    chat_id = models.CharField(max_length=255, blank=True)
    message_id = models.CharField(max_length=255, blank=True)
    payload_snapshot = models.JSONField(default=dict)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Dispatch {self.status} for order #{self.order.public_id}"


class OrderTelegramNotifyLog(TimeStampedModel):
    class Kind(models.TextChoices):
        NEW_ORDER = "new_order", "New order"
        MANUAL_ORDER = "manual_order", "Manual order"
        PREORDER_PAID = "preorder_paid", "Preorder paid"
        PREORDER_FULFILLED = "preorder_fulfilled", "Preorder fulfilled"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="tg_notify_logs"
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.QUEUED
    )
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    payload_snapshot = models.JSONField(default=dict, blank=True)
    response_snapshot = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "created_at"), name="ord_tg_log_status_idx"),
            models.Index(fields=("order", "kind"), name="ord_tg_log_order_kind_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.status} for order #{self.order.public_id}"
