import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0012_productcard_public_tags_search_hints"),
        ("orders", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="checkout_idempotency_key",
            field=models.CharField(
                blank=True,
                help_text="Client-supplied key to make checkout order creation idempotent.",
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["checkout_idempotency_key"],
                name="order_checkout_idem_idx",
            ),
        ),
        migrations.CreateModel(
            name="OrderStatusLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("from_status", models.CharField(blank=True, max_length=30)),
                ("to_status", models.CharField(max_length=30)),
                ("actor", models.CharField(blank=True, default="", max_length=64)),
                ("note", models.CharField(blank=True, default="", max_length=255)),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="status_logs",
                        to="orders.order",
                    ),
                ),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.AddIndex(
            model_name="orderstatuslog",
            index=models.Index(
                fields=["order", "created_at"],
                name="ord_stlog_ord_created_idx",
            ),
        ),
        migrations.CreateModel(
            name="OrderItemDigitalItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "digital_item",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="order_item_link",
                        to="catalog.digitalitem",
                    ),
                ),
                (
                    "order_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reserved_digital_items",
                        to="orders.orderitem",
                    ),
                ),
            ],
            options={"ordering": ("id",)},
        ),
        migrations.AddConstraint(
            model_name="orderitemdigitalitem",
            constraint=models.UniqueConstraint(
                fields=("order_item", "digital_item"),
                name="order_item_digital_item_unique",
            ),
        ),
    ]
