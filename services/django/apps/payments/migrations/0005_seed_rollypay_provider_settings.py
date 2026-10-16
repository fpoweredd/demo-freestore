# Seed RollyPay provider row (disabled until admin enables).

from decimal import Decimal

from django.db import migrations


def seed_rollypay(apps, schema_editor):
    PaymentProviderSettings = apps.get_model("payments", "PaymentProviderSettings")
    PaymentProviderSettings.objects.get_or_create(
        provider_id="rollypay",
        defaults={
            "is_enabled": False,
            "show_on_product_page": True,
            "product_min_amount": Decimal("0.00"),
            "balance_topup_min_amount": Decimal("10.00"),
            "balance_topup_max_amount": Decimal("1000000.00"),
            "ui_sort_order": 50,
        },
    )


def unseed_rollypay(apps, schema_editor):
    PaymentProviderSettings = apps.get_model("payments", "PaymentProviderSettings")
    PaymentProviderSettings.objects.filter(provider_id="rollypay").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0004_wallettransaction_paymentrefund"),
    ]

    operations = [
        migrations.RunPython(seed_rollypay, unseed_rollypay),
    ]
