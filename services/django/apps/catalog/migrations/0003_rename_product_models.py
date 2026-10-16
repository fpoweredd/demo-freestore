# Generated manually for model rename refactor.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_alter_category_options"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="productattribute",
            name="product_attribute_unique",
        ),
        migrations.RemoveIndex(
            model_name="digitalitem",
            name="digital_variant_used_idx",
        ),
        migrations.RemoveIndex(
            model_name="productvariant",
            name="variant_prod_active_idx",
        ),
        migrations.RenameModel(
            old_name="Product",
            new_name="ProductCard",
        ),
        migrations.RenameField(
            model_name="productattribute",
            old_name="product",
            new_name="product_card",
        ),
        migrations.RenameField(
            model_name="productvariant",
            old_name="product",
            new_name="product_card",
        ),
        migrations.RenameModel(
            old_name="ProductVariant",
            new_name="Product",
        ),
        migrations.RenameField(
            model_name="digitalitem",
            old_name="variant",
            new_name="product",
        ),
        migrations.AlterField(
            model_name="product",
            name="product_card",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="products",
                to="catalog.productcard",
            ),
        ),
        migrations.AlterModelOptions(
            name="productcard",
            options={
                "ordering": ("-created_at",),
                "verbose_name": "Product card",
                "verbose_name_plural": "Product cards",
            },
        ),
        migrations.AlterModelOptions(
            name="product",
            options={
                "ordering": ("id",),
                "verbose_name": "Product",
                "verbose_name_plural": "Products",
            },
        ),
        migrations.AddIndex(
            model_name="digitalitem",
            index=models.Index(fields=["product", "is_used"], name="digital_variant_used_idx"),
        ),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(fields=["product_card", "is_active"], name="variant_prod_active_idx"),
        ),
        migrations.AddConstraint(
            model_name="productattribute",
            constraint=models.UniqueConstraint(
                fields=("product_card", "key", "value"),
                name="product_attribute_unique",
            ),
        ),
    ]
