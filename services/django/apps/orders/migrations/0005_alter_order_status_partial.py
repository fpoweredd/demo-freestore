from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0004_alter_order_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "В обработке"),
                    ("awaiting_payment", "Ожидает оплаты"),
                    ("paid", "Оплачен"),
                    ("waiting_stock", "Отправлен в обработку"),
                    ("partially_fulfilled", "Частично обработан"),
                    ("manual_pending", "Отправлен в исполнение"),
                    ("completed", "Завершен"),
                    ("cancelled", "Отменён"),
                ],
                default="pending",
                max_length=30,
            ),
        ),
    ]
