from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0010_productcard_ui_labels"),
    ]

    operations = [
        migrations.AddField(
            model_name="homepagecategorysection",
            name="card_caption_template",
            field=models.CharField(
                blank=True,
                default="{category}",
                help_text="Template for subtitle under cards in this section. Supported placeholders: {category}, {name}, {price}, {buyers}, {fulfillment}.",
                max_length=255,
            ),
        ),
    ]

