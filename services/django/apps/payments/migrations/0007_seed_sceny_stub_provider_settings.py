# Seed UI stub payment provider (enabled; checkout blocked until real integration).

from __future__ import annotations

from django.db import migrations


def seed_stub(apps, schema_editor):
    PaymentProviderSettings = apps.get_model("payments", "PaymentProviderSettings")
    # Drop mistaken "sceny" seed if an earlier local run applied it under that name.
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


def unseed_stub(apps, schema_editor):
    PaymentProviderSettings = apps.get_model("payments", "PaymentProviderSettings")
    PaymentProviderSettings.objects.filter(provider_id__in=["stub", "sceny"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0006_seed_enot_provider_settings"),
    ]

    operations = [
        migrations.RunPython(seed_stub, unseed_stub),
    ]
