from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0009_productcard_unique_buyers_count_homepagesection"),
    ]

    operations = [
        migrations.AddField(
            model_name="productcard",
            name="ui_labels",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

