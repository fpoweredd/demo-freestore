from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

import apps.core.snowflake


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0002_order_checkout_idempotency_key_orderstatuslog_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("catalog", "0013_productcard_preorders_and_reservations_flags"),
    ]

    operations = [
        migrations.CreateModel(
            name="PreOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("public_id", models.BigIntegerField(db_index=True, default=apps.core.snowflake.generate_snowflake_id, editable=False, unique=True)),
                ("guest_email", models.EmailField(blank=True, max_length=254)),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("input_payload", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("paid", "Paid"), ("fulfilled", "Fulfilled"), ("cancelled", "Cancelled")], db_index=True, default="pending", max_length=20)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("fulfilled_at", models.DateTimeField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("order", models.OneToOneField(blank=True, help_text="Checkout-created order for this preorder (if any).", null=True, on_delete=django.db.models.deletion.CASCADE, related_name="preorder", to="orders.order")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="preorders", to="catalog.product")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="preorders", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("created_at", "id"),
            },
        ),
        migrations.AddIndex(
            model_name="preorder",
            index=models.Index(fields=["status", "created_at"], name="preord_stat_created_idx"),
        ),
        migrations.AddIndex(
            model_name="preorder",
            index=models.Index(fields=["product", "status", "created_at"], name="preord_prod_stat_cr_idx"),
        ),
    ]

