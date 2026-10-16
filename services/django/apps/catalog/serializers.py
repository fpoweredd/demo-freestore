from rest_framework import serializers

from .models import Category, Product, ProductCard, ProductInputField


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "slug", "parent", "icon", "is_active")


class ProductInputFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductInputField
        fields = (
            "id",
            "key",
            "label",
            "field_type",
            "is_required",
            "placeholder",
            "help_text",
            "sort_order",
            "min_value",
            "max_value",
            "regex",
            "is_active",
        )


class ProductCompactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = (
            "id",
            "price",
            "old_price",
            "stock_count",
            "is_active",
            "attributes",
            "image",
            "image_url",
            "is_image_pinned",
        )


class ProductCardSerializer(serializers.ModelSerializer):
    category = serializers.SlugRelatedField(read_only=True, slug_field="slug")
    input_fields = ProductInputFieldSerializer(read_only=True, many=True)
    products = ProductCompactSerializer(read_only=True, many=True)
    default_product_id = serializers.IntegerField(source="default_product_id", read_only=True)
    tags = serializers.SerializerMethodField()

    class Meta:
        model = ProductCard
        fields = (
            "id",
            "category",
            "name",
            "slug",
            "description",
            "tags",
            "fulfillment_mode",
            "default_product_id",
            "image",
            "image_url",
            "is_image_pinned",
            "is_hidden",
            "is_active",
            "is_featured",
            "input_fields",
            "products",
        )

    def get_tags(self, obj):
        raw = getattr(obj, "public_tags", "") or ""
        return [x.strip() for x in raw.split(",") if x.strip()]


class ProductSerializer(serializers.ModelSerializer):
    product_card = ProductCardSerializer(read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "product_card",
            "attributes",
            "image",
            "image_url",
            "is_image_pinned",
            "is_hidden",
            "price",
            "old_price",
            "stock_count",
            "is_active",
            "created_at",
        )
