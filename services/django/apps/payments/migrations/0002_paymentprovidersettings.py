# Generated manually for PaymentProviderSettings

from decimal import Decimal

from django.db import migrations, models


def seed_nowpayments(apps, schema_editor):
    PaymentProviderSettings = apps.get_model("payments", "PaymentProviderSettings")
    PaymentProviderSettings.objects.get_or_create(
        provider_id="nowpayments",
        defaults={
            "is_enabled": False,
            "balance_topup_min_amount": Decimal("10.00"),
            "balance_topup_max_amount": Decimal("1000000.00"),
        },
    )


def unseed_nowpayments(apps, schema_editor):
    PaymentProviderSettings = apps.get_model("payments", "PaymentProviderSettings")
    PaymentProviderSettings.objects.filter(provider_id="nowpayments").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentProviderSettings",
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
                ("provider_id", models.CharField(db_index=True, max_length=32, unique=True)),
                (
                    "is_enabled",
                    models.BooleanField(
                        default=False,
                        help_text="If off, this provider is hidden in the balance page and rejects API top-up/init.",
                    ),
                ),
                (
                    "balance_topup_min_amount",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("10.00"),
                        help_text="Minimum balance top-up amount (RUB) for this provider.",
                        max_digits=12,
                    ),
                ),
                (
                    "balance_topup_max_amount",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("1000000.00"),
                        help_text="Maximum balance top-up amount (RUB) for this provider.",
                        max_digits=12,
                    ),
                ),
            ],
            options={
                "verbose_name": "Payment provider settings",
                "verbose_name_plural": "Payment provider settings",
            },
        ),
        migrations.RunPython(seed_nowpayments, unseed_nowpayments),
    ]
