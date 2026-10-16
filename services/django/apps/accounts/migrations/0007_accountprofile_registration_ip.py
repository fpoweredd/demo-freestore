from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_alter_accountprofile_balance"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountprofile",
            name="registration_ip",
            field=models.GenericIPAddressField(
                blank=True,
                null=True,
                help_text="Client IP captured once at account creation (first registration / OAuth signup).",
            ),
        ),
    ]
