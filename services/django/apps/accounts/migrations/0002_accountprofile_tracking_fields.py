from django.db import migrations, models
import django.db.models.deletion

import apps.core.snowflake


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountprofile",
            name="public_id",
            field=models.BigIntegerField(
                default=apps.core.snowflake.generate_snowflake_id,
                editable=False,
                unique=True,
                db_index=True,
            ),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="generated_username",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="tg_username",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="tg_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="role",
            field=models.CharField(
                choices=[
                    ("superuser", "Superuser"),
                    ("admin", "Admin"),
                    ("staff", "Staff"),
                    ("partner", "Partner"),
                    ("buyer", "Buyer"),
                    ("customer", "Customer"),
                ],
                default="customer",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="location",
            field=models.CharField(blank=True, default="", max_length=2),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="last_active",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="marketing_agree",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="utm_params",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="last_session_key",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="last_ip",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="last_user_agent",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]

