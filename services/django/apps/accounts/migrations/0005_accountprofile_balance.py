from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_remove_accountprofile_location"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountprofile",
            name="balance",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0"),
                help_text="Current balance. Update only through services; add BalanceTransaction when payments go live.",
                max_digits=14,
            ),
        ),
    ]
