from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0007_product_is_hidden_productcard_is_hidden"),
    ]

    operations = [
        migrations.AddField(
            model_name="productcard",
            name="exclude_from_popular",
            field=models.BooleanField(default=False),
        ),
    ]

