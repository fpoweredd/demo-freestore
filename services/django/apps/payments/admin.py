from django.contrib import admin

from .models import (
    BalanceTopUp,
    Payment,
    PaymentProviderSettings,
    PaymentRefund,
    PaymentWebhookLog,
    WalletTransaction,
)


@admin.register(PaymentProviderSettings)
class PaymentProviderSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "provider_id",
        "is_enabled",
        "show_on_product_page",
        "ui_sort_order",
        "product_min_amount",
        "balance_topup_min_amount",
        "balance_topup_max_amount",
    )
    list_filter = ("is_enabled", "show_on_product_page")
    list_editable = ("is_enabled", "show_on_product_page", "ui_sort_order")
    list_display_links = ("provider_id",)
    search_fields = ("provider_id",)
    ordering = ("ui_sort_order", "provider_id")


@admin.register(BalanceTopUp)
class BalanceTopUpAdmin(admin.ModelAdmin):
    list_display = ("public_id", "user", "amount", "currency", "status", "created_at")
    list_filter = ("status", "currency")
    search_fields = ("public_id", "user__email")
    raw_id_fields = ("user",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "balance_top_up",
        "provider",
        "status",
        "provider_status",
        "amount",
        "currency",
        "provider_payment_id",
        "created_at",
    )
    list_filter = ("provider", "status")
    search_fields = (
        "provider_payment_id",
        "order__public_id",
        "balance_top_up__public_id",
    )
    raw_id_fields = ("order", "balance_top_up")


@admin.register(PaymentWebhookLog)
class PaymentWebhookLogAdmin(admin.ModelAdmin):
    list_display = ("id", "payment", "signature_valid", "processed_at", "created_at")
    list_filter = ("signature_valid",)
    raw_id_fields = ("payment",)


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "kind",
        "amount",
        "currency",
        "balance_before",
        "balance_after",
        "created_at",
    )
    list_filter = ("kind", "currency")
    search_fields = ("user__email", "source_id", "description")
    raw_id_fields = ("user",)


@admin.register(PaymentRefund)
class PaymentRefundAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "payment",
        "provider_refund_id",
        "amount",
        "currency",
        "status",
        "created_at",
    )
    list_filter = ("status", "currency")
    search_fields = ("provider_refund_id", "payment__provider_payment_id")
    raw_id_fields = ("payment",)
