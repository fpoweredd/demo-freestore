import json

from django.contrib import admin
from django.contrib import messages
from django import forms
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponseRedirect, JsonResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse

from apps.orders.models import PreOrder

from .forms import DigitalItemBulkUploadForm
from .models import Category, DigitalItem, HomepageCategorySection, Product, ProductAttribute, ProductCard, ProductInputField


def _paid_preorder_quantity_for_product(*, product_id: int) -> int:
    total = (
        PreOrder.objects.filter(product_id=product_id, status=PreOrder.Status.PAID).aggregate(
            total_qty=Sum("quantity")
        ).get("total_qty")
    )
    return int(total or 0)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "parent", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


class ProductInline(admin.TabularInline):
    model = Product
    extra = 0


class ProductAttributeInline(admin.TabularInline):
    model = ProductAttribute
    extra = 0


class ProductInputFieldInline(admin.TabularInline):
    model = ProductInputField
    extra = 0


class ProductCardAdminForm(forms.ModelForm):
    selector_axes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=(
            "Axes to show on product page. "
            "Use JSON: [\"region\", \"nominal\", \"variant\"] "
            "or plain CSV: region, nominal, variant. "
            "Hardcoded frontend axis keys: region, nominal, variant, platform, option, sku."
        ),
    )
    selector_value_order = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=(
            "Optional order for selector values by axis. "
            "JSON object only. Example: "
            '{"duration": ["1 month", "6 months", "1 year"], "type": ["Tinder Plus", "Tinder Gold"]}. '
            "Values not listed here are still shown after listed values. "
            "Their order is controlled by Product.sort_order."
        ),
    )

    class Meta:
        model = ProductCard
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get("instance")
        if instance and instance.pk:
            self.fields["default_product"].queryset = Product.objects.filter(product_card=instance, is_active=True)
            self.initial["selector_axes"] = ", ".join(instance.selector_axes or [])
            self.initial["selector_value_order"] = json.dumps(
                instance.selector_value_order or {},
                ensure_ascii=False,
                indent=2,
            )
        else:
            self.fields["default_product"].queryset = Product.objects.none()

    def clean_default_product(self):
        default_product = self.cleaned_data.get("default_product")
        if default_product and not default_product.is_active:
            raise forms.ValidationError("Default product must be active.")
        return default_product

    def clean_ui_labels(self):
        labels = self.cleaned_data.get("ui_labels") or {}
        if not isinstance(labels, dict):
            raise forms.ValidationError("ui_labels must be a JSON object.")
        return labels

    def clean_selector_axes(self):
        raw = str(self.cleaned_data.get("selector_axes") or "").strip()
        if not raw:
            return []
        axes: list[str]
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise forms.ValidationError(
                    "Invalid JSON. Example: [\"region\", \"nominal\", \"variant\"]"
                ) from exc
            if not isinstance(parsed, list):
                raise forms.ValidationError("JSON value must be an array.")
            axes = [str(x or "").strip() for x in parsed]
        else:
            axes = [x.strip() for x in raw.split(",")]
        out: list[str] = []
        for raw in axes:
            key = str(raw or "").strip().lower()
            if not key:
                continue
            if key in out:
                continue
            out.append(key)
        return out

    def clean_selector_value_order(self):
        raw = str(self.cleaned_data.get("selector_value_order") or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(
                "Invalid JSON object. Example: "
                '{"duration": ["1 month", "6 months", "1 year"]}'
            ) from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError("selector_value_order must be a JSON object.")
        out: dict[str, list[str]] = {}
        for raw_axis, raw_values in parsed.items():
            axis = str(raw_axis or "").strip().lower()
            if not axis:
                continue
            if not isinstance(raw_values, list):
                raise forms.ValidationError(
                    f'Axis "{axis}" must contain a JSON array of values.'
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
                out[axis] = values
        return out


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "product_card", "sort_order", "price", "stock_count", "is_active", "is_hidden", "is_image_pinned", "created_at")
    list_filter = ("is_active", "is_hidden", "product_card__category")
    search_fields = ("product_card__name", "product_card__slug", "id")


@admin.register(ProductCard)
class ProductCardAdmin(admin.ModelAdmin):
    form = ProductCardAdminForm
    list_display = (
        "id",
        "name",
        "slug",
        "category",
        "fulfillment_mode",
        "preorders_enabled",
        "use_reservations",
        "quantity_selection_enabled",
        "include_telegram_handle_field",
        "min_order_quantity",
        "max_order_quantity",
        "default_order_quantity",
        "default_product",
        "unique_buyers_count",
        "is_active",
        "is_hidden",
        "exclude_from_popular",
        "is_featured",
        "is_image_pinned",
        "created_at",
    )
    list_filter = (
        "is_active",
        "is_hidden",
        "exclude_from_popular",
        "is_featured",
        "fulfillment_mode",
        "preorders_enabled",
        "use_reservations",
        "quantity_selection_enabled",
        "include_telegram_handle_field",
        "category",
    )
    search_fields = (
        "name",
        "slug",
        "public_tags",
        "search_hints",
        "description",
        "description_md",
        "instruction_md",
    )
    prepopulated_fields = {"slug": ("name",)}
    inlines = (ProductInline, ProductAttributeInline, ProductInputFieldInline)


@admin.register(ProductAttribute)
class ProductAttributeAdmin(admin.ModelAdmin):
    list_display = ("id", "product_card", "key", "value", "created_at")
    list_filter = ("key",)
    search_fields = ("product_card__name", "key", "value")


@admin.register(ProductInputField)
class ProductInputFieldAdmin(admin.ModelAdmin):
    list_display = ("id", "product_card", "key", "label", "field_type", "is_required", "is_active", "sort_order")
    list_filter = ("field_type", "is_required", "is_active")
    search_fields = ("product_card__name", "key", "label")


@admin.register(HomepageCategorySection)
class HomepageCategorySectionAdmin(admin.ModelAdmin):
    list_display = ("id", "category", "title", "sort_order", "items_limit", "card_caption_template", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("category__name", "title")
    list_editable = ("sort_order", "items_limit", "card_caption_template", "is_active")


@admin.register(DigitalItem)
class DigitalItemAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "is_used", "reserved_at", "used_at", "created_at")
    list_filter = ("is_used",)
    search_fields = ("product__product_card__name",)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "bulk-upload/pending-preorders/",
                self.admin_site.admin_view(self.bulk_upload_pending_preorders_view),
                name="catalog_digitalitem_bulk_upload_pending_preorders",
            ),
            path(
                "bulk-upload/",
                self.admin_site.admin_view(self.bulk_upload_view),
                name="catalog_digitalitem_bulk_upload",
            ),
        ]
        return custom_urls + urls

    def bulk_upload_pending_preorders_view(self, request):
        if request.method != "GET":
            return JsonResponse({"detail": "Method not allowed"}, status=405)
        raw = (request.GET.get("product_id") or "").strip()
        if not raw.isdigit():
            return JsonResponse({"pending_qty": 0})
        pending_qty = _paid_preorder_quantity_for_product(product_id=int(raw))
        return JsonResponse({"pending_qty": pending_qty})

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["bulk_upload_url"] = reverse("admin:catalog_digitalitem_bulk_upload")
        return super().changelist_view(request, extra_context=extra_context)

    def bulk_upload_view(self, request):
        initial = {}
        product_id_raw = (request.GET.get("product_id") or "").strip()
        if product_id_raw.isdigit():
            initial["product"] = int(product_id_raw)
        if request.method == "POST":
            form = DigitalItemBulkUploadForm(request.POST)
            if form.is_valid():
                product = form.cleaned_data["product"]
                payloads = form.cleaned_data["payloads"]
                instances = [DigitalItem(product=product, payload_encrypted=payload) for payload in payloads]

                with transaction.atomic():
                    DigitalItem.objects.bulk_create(instances, batch_size=1000)
                    try:
                        from apps.orders.services import fulfill_waiting_stock_orders_for_product

                        fulfill_waiting_stock_orders_for_product(product=product)
                    except Exception:
                        # keep admin upload robust; failures should be handled by future periodic job
                        pass

                self.message_user(
                    request,
                    f"Uploaded {len(instances)} digital items for product #{product.id}.",
                    level=messages.SUCCESS,
                )
                return HttpResponseRedirect(reverse("admin:catalog_digitalitem_changelist"))
        else:
            form = DigitalItemBulkUploadForm(initial=initial)

        selected_product_id = None
        if request.method == "POST":
            post_pid = (request.POST.get("product") or "").strip()
            if post_pid.isdigit():
                selected_product_id = int(post_pid)
        if selected_product_id is None and product_id_raw.isdigit():
            selected_product_id = int(product_id_raw)

        pending_preorder_total = (
            _paid_preorder_quantity_for_product(product_id=selected_product_id)
            if selected_product_id is not None
            else 0
        )
        pending_preorders_url = reverse(
            "admin:catalog_digitalitem_bulk_upload_pending_preorders"
        )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Bulk upload digital items",
            "form": form,
            "pending_preorder_total": pending_preorder_total,
            "pending_preorders_url": pending_preorders_url,
        }
        return TemplateResponse(request, "admin/catalog/digitalitem/bulk_upload.html", context)
