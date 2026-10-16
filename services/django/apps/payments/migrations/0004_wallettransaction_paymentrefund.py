import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0003_paymentprovidersettings_product_page_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentRefund",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "provider_refund_id",
                    models.CharField(blank=True, db_index=True, max_length=128),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("currency", models.CharField(default="RUB", max_length=10)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("reason", models.CharField(blank=True, max_length=255)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "payment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="refunds",
                        to="payments.payment",
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="WalletTransaction",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("topup_credit", "Top-up credit"),
                            ("order_debit", "Order debit"),
                            ("refund_credit", "Refund credit"),
                            ("chargeback_debit", "Chargeback debit"),
                            ("manual_adjustment", "Manual adjustment"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "source_type",
                    models.CharField(
                        choices=[
                            ("payment", "Payment"),
                            ("refund", "Refund"),
                            ("order", "Order"),
                            ("manual", "Manual"),
                        ],
                        max_length=32,
                    ),
                ),
                ("source_id", models.CharField(max_length=64)),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="Signed amount. Positive = credit, negative = debit.",
                        max_digits=12,
                    ),
                ),
                ("currency", models.CharField(default="RUB", max_length=10)),
                (
                    "balance_before",
                    models.DecimalField(decimal_places=2, max_digits=14),
                ),
                ("balance_after", models.DecimalField(decimal_places=2, max_digits=14)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="wallet_transactions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddIndex(
            model_name="wallettransaction",
            index=models.Index(
                fields=["user", "-created_at"], name="wallet_tx_user_created_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="wallettransaction",
            index=models.Index(fields=["kind"], name="wallet_tx_kind_idx"),
        ),
        migrations.AddConstraint(
            model_name="paymentrefund",
            constraint=models.UniqueConstraint(
                condition=~models.Q(provider_refund_id=""),
                fields=("payment", "provider_refund_id"),
                name="payment_refund_unique_provider_refund_id",
            ),
        ),
        migrations.AddConstraint(
            model_name="wallettransaction",
            constraint=models.UniqueConstraint(
                fields=("source_type", "source_id", "kind"),
                name="wallet_tx_unique_source_kind",
            ),
        ),
    ]
