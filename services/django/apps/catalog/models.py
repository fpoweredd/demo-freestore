from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from apps.catalog.search_utils import normalize_csv_field


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Category(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    icon = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "Categories"
        indexes = [
            models.Index(fields=("slug",), name="category_slug_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class ProductCard(TimeStampedModel):
    class FulfillmentMode(models.TextChoices):
        INSTANT = "instant", "Instant"
        MANUAL = "manual", "Manual"

    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    description_md = models.TextField(
        blank=True,
        help_text="Markdown content for Description tab. If empty, legacy description is used.",
    )
    instruction_md = models.TextField(
        blank=True,
        help_text="Markdown content for Instruction tab.",
    )
    public_tags = models.TextField(
        blank=True,
        help_text="Comma-separated tags shown on the storefront; click filters catalog by tag.",
    )
    search_hints = models.TextField(
        blank=True,
        help_text="Comma-separated tags only for on-site search (not shown publicly).",
    )
    fulfillment_mode = models.CharField(
        max_length=20,
        choices=FulfillmentMode.choices,
        default=FulfillmentMode.INSTANT,
    )
    default_product = models.ForeignKey(
        "Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_cards",
    )
    image = models.ImageField(upload_to="catalog/product_cards/", blank=True, null=True)
    image_url = models.URLField(blank=True)
    is_image_pinned = models.BooleanField(default=False)
    is_hidden = models.BooleanField(
        default=False,
        help_text=(
            "Hide from catalog, categories, and on-site search. "
            "The card stays available by direct URL when Is active is on."
        ),
    )
    exclude_from_popular = models.BooleanField(default=False)
    ui_labels = models.JSONField(default=dict, blank=True)
    selector_axes = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Selection axes order for product page chips. "
            "Example: ['region', 'nominal', 'variant'] or ['platform', 'option', 'variant']. "
            "Use 'variant' to select by product id."
        ),
    )
    selector_value_order = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Optional explicit order for selector values by axis. "
            "Example: {'duration': ['1 month', '6 months', '1 year']}."
        ),
    )
    unique_buyers_count = models.PositiveIntegerField(default=0)
    preorders_enabled = models.BooleanField(
        default=True,
        help_text="If off, instant out-of-stock products cannot be purchased (no backorders).",
    )
    use_reservations = models.BooleanField(
        default=False,
        help_text="If on, instant digital items are reserved on order create (prevents oversell).",
    )
    quantity_selection_enabled = models.BooleanField(
        default=False,
        help_text="If on, buyer can choose quantity on product page.",
    )
    include_telegram_handle_field = models.BooleanField(
        default=False,
        help_text="If on, product page includes an extra TG Handler field (always rendered last).",
    )
    min_order_quantity = models.PositiveIntegerField(default=1)
    max_order_quantity = models.PositiveIntegerField(default=1)
    default_order_quantity = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Product card"
        verbose_name_plural = "Product cards"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("slug",), name="product_slug_idx"),
            models.Index(fields=("is_active",), name="product_active_idx"),
            models.Index(
                fields=("category", "is_active"), name="product_cat_active_idx"
            ),
        ]

    def clean(self):
        super().clean()
        if self.default_product and self.default_product.product_card_id != self.id:
            raise ValidationError(
                {"default_product": "Default product must belong to this product card."}
            )
        min_qty = int(self.min_order_quantity or 1)
        max_qty = int(self.max_order_quantity or 1)
        default_qty = int(self.default_order_quantity or 1)
        if min_qty < 1:
            raise ValidationError(
                {"min_order_quantity": "Minimum quantity must be at least 1."}
            )
        if max_qty < min_qty:
            raise ValidationError(
                {
                    "max_order_quantity": "Maximum quantity must be greater than or equal to minimum quantity."
                }
            )
        if default_qty < min_qty or default_qty > max_qty:
            raise ValidationError(
                {
                    "default_order_quantity": "Default quantity must be within min/max range."
                }
            )
        axes = self.selector_axes or []
        if not isinstance(axes, list):
            raise ValidationError({"selector_axes": "selector_axes must be a JSON array."})
        normalized: list[str] = []
        for raw in axes:
            key = str(raw or "").strip().lower()
            if not key:
                continue
            if key in normalized:
                continue
            normalized.append(key)
        self.selector_axes = normalized
        raw_value_order = self.selector_value_order or {}
        if not isinstance(raw_value_order, dict):
            raise ValidationError(
                {"selector_value_order": "selector_value_order must be a JSON object."}
            )
        normalized_value_order: dict[str, list[str]] = {}
        for raw_axis, raw_values in raw_value_order.items():
            axis_key = str(raw_axis or "").strip().lower()
            if not axis_key:
                continue
            if not isinstance(raw_values, list):
                raise ValidationError(
                    {
                        "selector_value_order": (
                            "selector_value_order values must be arrays of strings."
                        )
                    }
                )
            values: list[str] = []
            for raw_value in raw_values:
                value = str(raw_value or "").strip()
                if not value:
                    continue
                if value in values:
                    continue
                values.append(value)
            if values:
                normalized_value_order[axis_key] = values
        self.selector_value_order = normalized_value_order

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        self.public_tags = normalize_csv_field(self.public_tags)
        self.search_hints = normalize_csv_field(self.search_hints)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class HomepageCategorySection(TimeStampedModel):
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="homepage_sections"
    )
    title = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=100)
    items_limit = models.PositiveSmallIntegerField(default=8)
    card_caption_template = models.CharField(
        max_length=255,
        blank=True,
        default="{category}",
        help_text=(
            "Template for subtitle under cards in this section. "
            "Supported placeholders: {category}, {name}, {price}, {buyers}, {fulfillment}."
        ),
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("category",), name="homepage_section_category_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.title or self.category.name


class Product(TimeStampedModel):
    product_card = models.ForeignKey(
        ProductCard, on_delete=models.CASCADE, related_name="products"
    )
    attributes = models.JSONField(default=dict, blank=True)
    image = models.ImageField(upload_to="catalog/products/", blank=True, null=True)
    image_url = models.URLField(blank=True)
    is_image_pinned = models.BooleanField(default=False)
    is_hidden = models.BooleanField(
        default=False,
        help_text="Hide this SKU variant in the product-page selector (card may still be public).",
    )
    price = models.DecimalField(max_digits=12, decimal_places=2)
    old_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    sort_order = models.IntegerField(
        default=100,
        help_text="Lower value appears first in selector options and defaults.",
    )
    stock_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        ordering = ("sort_order", "id")
        indexes = [
            models.Index(
                fields=("product_card", "is_active"), name="variant_prod_active_idx"
            ),
            models.Index(
                fields=("product_card", "sort_order", "id"),
                name="variant_prod_sort_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product_card.name} #{self.id}"


class ProductAttribute(TimeStampedModel):
    product_card = models.ForeignKey(
        ProductCard, on_delete=models.CASCADE, related_name="metadata_attributes"
    )
    key = models.CharField(max_length=100)
    value = models.CharField(max_length=255)

    class Meta:
        ordering = ("key",)
        constraints = [
            models.UniqueConstraint(
                fields=("product_card", "key", "value"), name="product_attribute_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product_card.name}: {self.key}={self.value}"


class ProductInputField(TimeStampedModel):
    class FieldType(models.TextChoices):
        TEXT = "text", "Text"
        TEXTAREA = "textarea", "Textarea"
        NUMBER = "number", "Number"
        EMAIL = "email", "Email"
        PASSWORD = "password", "Password"

    product_card = models.ForeignKey(
        ProductCard, on_delete=models.CASCADE, related_name="input_fields"
    )
    key = models.SlugField(max_length=100)
    label = models.CharField(max_length=255)
    field_type = models.CharField(
        max_length=20, choices=FieldType.choices, default=FieldType.TEXT
    )
    is_required = models.BooleanField(default=True)
    placeholder = models.CharField(max_length=255, blank=True)
    help_text = models.CharField(max_length=500, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    min_value = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    max_value = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    regex = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("product_card", "key"),
                name="product_input_field_card_key_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=("product_card", "is_active"),
                name="product_input_card_active_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValidationError(
                {"max_value": "max_value must be greater than or equal to min_value."}
            )

    def __str__(self) -> str:
        return f"{self.product_card.name}: {self.label}"


class DigitalItem(TimeStampedModel):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="digital_items"
    )
    payload_encrypted = models.TextField()
    is_used = models.BooleanField(default=False)
    reserved_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("id",)
        indexes = [
            models.Index(
                fields=("product", "is_used"), name="digital_variant_used_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"DigitalItem #{self.id} ({'used' if self.is_used else 'ready'})"
