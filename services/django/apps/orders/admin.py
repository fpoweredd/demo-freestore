from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    ManualDispatchLog,
    Order,
    OrderItem,
    OrderItemInput,
    OrderTelegramNotifyLog,
    PreOrder,
)
from .services import complete_manual_order, retry_order_telegram_notify


class OrderItemInputInline(admin.TabularInline):
    model = OrderItemInput
    extra = 0
    readonly_fields = ("input_field", "value")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "quantity", "unit_price", "total_price", "input_payload")
    show_change_link = True


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "public_id",
        "status",
        "total",
        "currency",
        "guest_email",
        "created_at",
        "operator_actions",
    )
    list_filter = ("status", "currency")
    search_fields = ("public_id", "guest_email")
    inlines = (OrderItemInline,)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:order_id>/complete-manual/",
                self.admin_site.admin_view(self.complete_manual_view),
                name="orders_order_complete_manual",
            )
        ]
        return custom + urls

    def operator_actions(self, obj: Order):
        recipient = (
            (getattr(obj.user, "email", "") or "").strip() if obj.user_id else ""
        ) or (obj.guest_email or "").strip()
        links: list[str] = []
        if obj.status == Order.Status.MANUAL_PENDING:
            complete_url = reverse("admin:orders_order_complete_manual", args=[obj.id])
            links.append(
                f'<a class="button" href="{complete_url}" style="padding:3px 8px;">Fulfill</a>'
            )
        if recipient:
            subject = f"Order {obj.public_id} details"
            mailto = f"mailto:{recipient}?subject={subject}"
            links.append(
                f'<a class="button" href="{mailto}" style="padding:3px 8px;">Contact by email</a>'
            )
        if not links:
            return "-"
        return format_html("{}", mark_safe(" ".join(links)))

    operator_actions.short_description = "Operator actions"

    def complete_manual_view(self, request, order_id: int):
        order = get_object_or_404(Order, pk=order_id)
        complete_manual_order(order, actor=f"admin:{request.user.pk}")
        self.message_user(request, f"Order #{order.public_id} marked as completed.", level=messages.SUCCESS)
        return redirect(request.META.get("HTTP_REFERER") or reverse("admin:orders_order_changelist"))


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "product", "quantity", "unit_price", "total_price")
    search_fields = ("order__public_id",)
    inlines = (OrderItemInputInline,)


@admin.register(ManualDispatchLog)
class ManualDispatchLogAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "status", "chat_id", "message_id", "sent_at", "created_at")
    list_filter = ("status",)
    search_fields = ("order__public_id", "chat_id", "message_id")


@admin.register(OrderTelegramNotifyLog)
class OrderTelegramNotifyLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "kind",
        "status",
        "attempts",
        "max_attempts",
        "sent_at",
        "last_attempt_at",
        "created_at",
    )
    list_filter = ("kind", "status")
    search_fields = ("order__public_id", "error_message")
    actions = ("retry_selected",)

    @admin.action(description="Retry selected telegram notifications")
    def retry_selected(self, request, queryset):
        ok = 0
        failed = 0
        for row in queryset:
            if retry_order_telegram_notify(row):
                ok += 1
            else:
                failed += 1
        self.message_user(
            request,
            f"Retry done. Success: {ok}, failed: {failed}.",
            level=messages.INFO if failed == 0 else messages.WARNING,
        )


@admin.register(PreOrder)
class PreOrderAdmin(admin.ModelAdmin):
    list_display = ("id", "public_id", "status", "product", "quantity", "order", "user", "guest_email", "created_at")
    list_filter = ("status", "product")
    search_fields = ("public_id", "order__public_id", "guest_email", "user__email")
