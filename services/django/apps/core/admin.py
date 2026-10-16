from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import ShopSettings


@admin.register(ShopSettings)
class ShopSettingsAdmin(admin.ModelAdmin):
    list_display = ("maintenance_mode", "buy_enabled", "refill_enabled", "updated_at")
    readonly_fields = ("updated_at", "operator_notes")
    fieldsets = (
        (
            "Global switches",
            {
                "fields": (
                    "maintenance_mode",
                    "buy_enabled",
                    "refill_enabled",
                )
            },
        ),
        (
            "Operator notes",
            {
                "fields": ("operator_notes", "updated_at"),
            },
        ),
    )

    def has_add_permission(self, request):
        if ShopSettings.objects.exists():
            return False
        return super().has_add_permission(request)

    @admin.display(description="What each toggle does")
    def operator_notes(self, _obj):
        html = (
            "<ul style='margin:0 0 0 18px;padding:0;line-height:1.5;'>"
            "<li><b>maintenance_mode</b>: show maintenance state for storefront users.</li>"
            "<li><b>buy_enabled</b>: block/unblock new order creation on product pages.</li>"
            "<li><b>refill_enabled</b>: block/unblock balance top-up operations.</li>"
            "<li><b>Safe defaults</b>: maintenance_mode=False, buy_enabled=True, refill_enabled=True.</li>"
            "</ul>"
        )
        # Django 6+: format_html needs at least one format arg; trusted static admin markup.
        return format_html("{0}", mark_safe(html))
