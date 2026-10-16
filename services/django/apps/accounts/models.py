from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string

from apps.core.snowflake import generate_snowflake_id


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AccountProfile(TimeStampedModel):
    class Role(models.TextChoices):
        SUPERUSER = "superuser", "Superuser"
        ADMIN = "admin", "Admin"
        STAFF = "staff", "Staff"
        PARTNER = "partner", "Partner"
        BUYER = "buyer", "Buyer"
        CUSTOMER = "customer", "Customer"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_profile",
    )
    public_id = models.BigIntegerField(
        default=generate_snowflake_id, unique=True, db_index=True, editable=False
    )
    generated_username = models.BooleanField(default=False)
    tg_username = models.CharField(max_length=150, blank=True, default="")
    tg_id = models.BigIntegerField(null=True, blank=True)
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.CUSTOMER)
    telegram_handle = models.CharField(max_length=64, blank=True)
    require_password_after_oauth = models.BooleanField(default=True)
    ip_geo = models.CharField(max_length=2, blank=True, default="")
    locale = models.CharField(max_length=32, blank=True, default="")
    last_active = models.DateTimeField(null=True, blank=True)
    marketing_agree = models.BooleanField(default=False)
    utm_params = models.JSONField(default=dict, blank=True)
    last_session_key = models.CharField(max_length=64, blank=True, default="")
    registration_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Client IP at first account creation (never overwritten).",
    )
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    last_user_agent = models.CharField(max_length=255, blank=True, default="")
    balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Current wallet balance snapshot. Update only through wallet transaction services.",
    )

    class Meta:
        indexes = [
            models.Index(fields=("telegram_handle",), name="account_tg_handle_idx")
        ]

    def __str__(self) -> str:
        return f"Profile for {self.user_id}"


class AccountIdentity(TimeStampedModel):
    class Provider(models.TextChoices):
        GOOGLE = "google", "Google"
        TELEGRAM = "telegram", "Telegram"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_identities",
    )
    provider = models.CharField(max_length=30, choices=Provider.choices)
    provider_uid = models.CharField(max_length=255)
    email_hint = models.EmailField(blank=True)
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "provider_uid"),
                name="account_identity_provider_uid_unique",
            ),
        ]
        indexes = [
            models.Index(fields=("user", "provider"), name="acct_ident_user_prov_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.provider_uid}"


class PasswordResetRequest(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_reset_requests",
    )
    email_snapshot = models.EmailField()
    token = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("token",), name="password_reset_token_idx"),
            models.Index(fields=("expires_at",), name="password_reset_expires_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = get_random_string(48)
        super().save(*args, **kwargs)

    @property
    def is_valid(self) -> bool:
        return self.consumed_at is None and self.expires_at > timezone.now()

    def __str__(self) -> str:
        return f"Password reset for user {self.user_id}"
