from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0005_alter_order_status_partial"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="utm_params",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="preorder",
            name="utm_params",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
