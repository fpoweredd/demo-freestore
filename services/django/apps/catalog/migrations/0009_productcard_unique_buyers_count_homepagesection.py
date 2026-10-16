from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0008_productcard_exclude_from_popular"),
    ]

    operations = [
        migrations.AddField(
            model_name="productcard",
            name="unique_buyers_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="HomepageCategorySection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(blank=True, max_length=255)),
                ("sort_order", models.PositiveIntegerField(default=100)),
                ("items_limit", models.PositiveSmallIntegerField(default=8)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "category",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="homepage_sections", to="catalog.category"),
                ),
            ],
            options={
                "ordering": ("sort_order", "id"),
                "constraints": [
                    models.UniqueConstraint(fields=("category",), name="homepage_section_category_unique"),
                ],
            },
        ),
    ]

