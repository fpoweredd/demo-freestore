from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0013_productcard_preorders_and_reservations_flags"),
    ]

    operations = [
        migrations.AddField(
            model_name="productcard",
            name="default_order_quantity",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="productcard",
            name="max_order_quantity",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="productcard",
            name="min_order_quantity",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="productcard",
            name="quantity_selection_enabled",
            field=models.BooleanField(
                default=False,
                help_text="If on, buyer can choose quantity on product page.",
            ),
        ),
    ]
