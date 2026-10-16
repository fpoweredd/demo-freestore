from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0015_productcard_include_telegram_handle_field"),
    ]

    operations = [
        migrations.AddField(
            model_name="productcard",
            name="description_md",
            field=models.TextField(
                blank=True,
                help_text="Markdown content for Description tab. If empty, legacy description is used.",
            ),
        ),
        migrations.AddField(
            model_name="productcard",
            name="instruction_md",
            field=models.TextField(
                blank=True,
                help_text="Markdown content for Instruction tab.",
            ),
        ),
        migrations.AddField(
            model_name="productcard",
            name="selector_axes",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Selection axes order for product page chips. Example: ['region', 'nominal', 'variant'] or ['platform', 'option', 'variant']. Use 'variant' to select by product id.",
            ),
        ),
    ]
