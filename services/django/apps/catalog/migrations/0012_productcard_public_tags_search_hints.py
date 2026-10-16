from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0011_homepagesection_card_caption_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="productcard",
            name="public_tags",
            field=models.TextField(
                blank=True,
                help_text="Comma-separated tags shown on the storefront; click filters catalog by tag.",
            ),
        ),
        migrations.AddField(
            model_name="productcard",
            name="search_hints",
            field=models.TextField(
                blank=True,
                help_text="Comma-separated tags only for on-site search (not shown publicly).",
            ),
        ),
    ]
