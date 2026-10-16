from rest_framework import serializers

from .models import ManualDispatchLog, Order, OrderItem, OrderStatusLog


class OrderItemInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, default=1)
    inputs = serializers.DictField(child=serializers.CharField(), required=False)


class QuoteRequestSerializer(serializers.Serializer):
    currency = serializers.CharField(default="USD")
    items = OrderItemInputSerializer(many=True)


class OrderCreateSerializer(QuoteRequestSerializer):
    guest_email = serializers.EmailField(required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=64, required=False, allow_blank=True)


class OrderItemSerializer(serializers.ModelSerializer):
    reserved_digital_items_count = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = (
            "id",
            "product",
            "quantity",
            "unit_price",
            "total_price",
            "input_payload",
            "reserved_digital_items_count",
        )

    def get_reserved_digital_items_count(self, obj: OrderItem) -> int:
        return obj.reserved_digital_items.count()


class OrderStatusLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderStatusLog
        fields = ("id", "from_status", "to_status", "actor", "note", "created_at")


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    status_logs = OrderStatusLogSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "public_id",
            "status",
            "total",
            "currency",
            "guest_email",
            "created_at",
            "items",
            "status_logs",
        )


class ManualDispatchLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ManualDispatchLog
        fields = ("id", "status", "chat_id", "message_id", "payload_snapshot", "error_message", "sent_at", "created_at")
