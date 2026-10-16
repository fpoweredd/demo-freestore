from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_paymentprovidersettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentprovidersettings",
            name="product_min_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0"),
                help_text="Hide provider on product page when selected product price is below this amount (RUB).",
                max_digits=12,
            ),
        ),
        migrations.AddField(
            model_name="paymentprovidersettings",
            name="show_on_product_page",
            field=models.BooleanField(
                default=True,
                help_text="If off, provider is hidden on product checkout and remains available only for balance top-up.",
            ),
        ),
        migrations.AddField(
            model_name="paymentprovidersettings",
            name="ui_sort_order",
            field=models.PositiveIntegerField(
                default=100,
                help_text="Display order in payment buttons (lower values are shown first).",
            ),
        ),
    ]
