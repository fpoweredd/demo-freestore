# Seed Enot provider row (disabled until admin enables).

from __future__ import annotations

from django.db import migrations


def seed_enot(apps, schema_editor):
    PaymentProviderSettings = apps.get_model("payments", "PaymentProviderSettings")
    PaymentProviderSettings.objects.get_or_create(
        provider_id="enot",
        defaults={
            "is_enabled": False,
            "show_on_product_page": False,
            "product_min_amount": "10.00",
            "balance_topup_min_amount": "10.00",
            "balance_topup_max_amount": "100000.00",
            "ui_sort_order": 30,
        },
    )


def unseed_enot(apps, schema_editor):
    PaymentProviderSettings = apps.get_model("payments", "PaymentProviderSettings")
    PaymentProviderSettings.objects.filter(provider_id="enot").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0005_seed_rollypay_provider_settings"),
    ]

    operations = [
        migrations.RunPython(seed_enot, unseed_enot),
    ]
