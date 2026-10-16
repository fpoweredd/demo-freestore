from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0016_productcard_selector_axes_and_markdown_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="productcard",
            name="selector_value_order",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Optional explicit order for selector values by axis. Example: {'duration': ['1 месяц', '6 месяцев', '1 год']}.",
            ),
        ),
    ]
