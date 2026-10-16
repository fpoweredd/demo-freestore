from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("telegram_handle", models.CharField(blank=True, max_length=64)),
                ("require_password_after_oauth", models.BooleanField(default=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="account_profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="PasswordResetRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("email_snapshot", models.EmailField(max_length=254)),
                ("token", models.CharField(editable=False, max_length=64, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="password_reset_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="AccountIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("provider", models.CharField(choices=[("google", "Google"), ("telegram", "Telegram")], max_length=30)),
                ("provider_uid", models.CharField(max_length=255)),
                ("email_hint", models.EmailField(blank=True, max_length=254)),
                ("meta", models.JSONField(blank=True, default=dict)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="account_identities",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="accountprofile",
            index=models.Index(fields=["telegram_handle"], name="account_tg_handle_idx"),
        ),
        migrations.AddIndex(
            model_name="passwordresetrequest",
            index=models.Index(fields=["token"], name="password_reset_token_idx"),
        ),
        migrations.AddIndex(
            model_name="passwordresetrequest",
            index=models.Index(fields=["expires_at"], name="password_reset_expires_idx"),
        ),
        migrations.AddConstraint(
            model_name="accountidentity",
            constraint=models.UniqueConstraint(fields=("provider", "provider_uid"), name="account_identity_provider_uid_unique"),
        ),
        migrations.AddIndex(
            model_name="accountidentity",
            index=models.Index(fields=["user", "provider"], name="acct_ident_user_prov_idx"),
        ),
    ]
