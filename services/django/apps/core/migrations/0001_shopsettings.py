from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ShopSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("maintenance_mode", models.BooleanField(default=False, help_text="If enabled, storefront is in maintenance mode.")),
                ("buy_enabled", models.BooleanField(default=True, help_text="If disabled, new checkout/order creation is blocked.")),
                ("refill_enabled", models.BooleanField(default=True, help_text="If disabled, balance top-up is blocked.")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Shop settings",
                "verbose_name_plural": "Shop settings",
            },
        ),
    ]
