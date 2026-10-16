from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_accountprofile_ip_geo_and_locale"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="accountprofile",
            name="location",
        ),
    ]

