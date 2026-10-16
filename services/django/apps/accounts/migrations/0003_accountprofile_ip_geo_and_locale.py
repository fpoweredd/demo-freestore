from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_accountprofile_tracking_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountprofile",
            name="ip_geo",
            field=models.CharField(blank=True, default="", max_length=2),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="locale",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
    ]

