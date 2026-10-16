# Rename mistaken "sceny" stub provider_id → "stub" (no Sceny product code).

from __future__ import annotations

from django.db import migrations


def rename_sceny_to_stub(apps, schema_editor):
    PaymentProviderSettings = apps.get_model("payments", "PaymentProviderSettings")
    PaymentProviderSettings.objects.filter(provider_id="sceny").delete()
    PaymentProviderSettings.objects.get_or_create(
        provider_id="stub",
        defaults={
            "is_enabled": True,
            "show_on_product_page": True,
            "product_min_amount": "1.00",
            "balance_topup_min_amount": "1.00",
            "balance_topup_max_amount": "100000.00",
            "ui_sort_order": 40,
        },
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0007_seed_sceny_stub_provider_settings"),
    ]

    operations = [
        migrations.RunPython(rename_sceny_to_stub, noop_reverse),
    ]
