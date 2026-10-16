from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0006_order_utm_params"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrderTelegramNotifyLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("kind", models.CharField(choices=[("new_order", "New order"), ("manual_order", "Manual order"), ("preorder_paid", "Preorder paid"), ("preorder_fulfilled", "Preorder fulfilled")], max_length=32)),
                ("status", models.CharField(choices=[("queued", "Queued"), ("sent", "Sent"), ("failed", "Failed")], default="queued", max_length=20)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("max_attempts", models.PositiveIntegerField(default=5)),
                ("payload_snapshot", models.JSONField(blank=True, default=dict)),
                ("response_snapshot", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("order", models.ForeignKey(on_delete=models.CASCADE, related_name="tg_notify_logs", to="orders.order")),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="ordertelegramnotifylog",
            index=models.Index(fields=["status", "created_at"], name="ord_tg_log_status_idx"),
        ),
        migrations.AddIndex(
            model_name="ordertelegramnotifylog",
            index=models.Index(fields=["order", "kind"], name="ord_tg_log_order_kind_idx"),
        ),
    ]

