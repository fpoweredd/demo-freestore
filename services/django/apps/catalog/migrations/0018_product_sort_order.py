from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0017_productcard_selector_value_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="sort_order",
            field=models.IntegerField(
                default=100,
                help_text="Lower value appears first in selector options and defaults.",
            ),
        ),
        migrations.AlterModelOptions(
            name="product",
            options={
                "ordering": ("sort_order", "id"),
                "verbose_name": "Product",
                "verbose_name_plural": "Products",
            },
        ),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(
                fields=("product_card", "sort_order", "id"),
                name="variant_prod_sort_idx",
            ),
        ),
    ]
