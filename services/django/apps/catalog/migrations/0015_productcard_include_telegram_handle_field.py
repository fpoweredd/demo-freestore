from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0014_productcard_quantity_controls"),
    ]

    operations = [
        migrations.AddField(
            model_name="productcard",
            name="include_telegram_handle_field",
            field=models.BooleanField(
                default=False,
                help_text="If on, product page includes an extra TG Handler field (always rendered last).",
            ),
        ),
    ]

