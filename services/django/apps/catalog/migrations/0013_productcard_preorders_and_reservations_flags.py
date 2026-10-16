from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0012_productcard_public_tags_search_hints"),
    ]

    operations = [
        migrations.AddField(
            model_name="productcard",
            name="preorders_enabled",
            field=models.BooleanField(
                default=True,
                help_text="If off, instant out-of-stock products cannot be purchased (no backorders).",
            ),
        ),
        migrations.AddField(
            model_name="productcard",
            name="use_reservations",
            field=models.BooleanField(
                default=False,
                help_text="If on, instant digital items are reserved on order create (prevents oversell).",
            ),
        ),
    ]

