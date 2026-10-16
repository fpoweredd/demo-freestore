from django.contrib import admin

from .models import AccountIdentity, AccountProfile, PasswordResetRequest


@admin.register(AccountProfile)
class AccountProfileAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "public_id",
        "user",
        "balance",
        "user_date_joined",
        "registration_ip",
        "role",
        "reg_geo_ip",
        "locale",
        "telegram_handle",
        "tg_username",
        "tg_id",
        "require_password_after_oauth",
        "last_active",
        "created_at",
        "updated_at",
    )
    list_filter = ("require_password_after_oauth", "role", "ip_geo", "marketing_agree")
    search_fields = (
        "user__username",
        "user__email",
        "telegram_handle",
        "tg_username",
        "public_id",
    )

    @admin.display(description="registered_at", ordering="user__date_joined")
    def user_date_joined(self, obj):
        return obj.user.date_joined

    @admin.display(description="reg_geo_ip", ordering="ip_geo")
    def reg_geo_ip(self, obj):
        return obj.ip_geo


@admin.register(AccountIdentity)
class AccountIdentityAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "provider",
        "provider_uid",
        "email_hint",
        "created_at",
    )
    list_filter = ("provider",)
    search_fields = ("provider_uid", "email_hint", "user__email", "user__username")


@admin.register(PasswordResetRequest)
class PasswordResetRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "email_snapshot",
        "token",
        "expires_at",
        "consumed_at",
        "created_at",
    )
    list_filter = ("consumed_at",)
    search_fields = ("token", "email_snapshot", "user__email")
