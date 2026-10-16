import json
from decimal import Decimal

from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from rest_framework import mixins, viewsets

from apps.orders.models import Order
from apps.core.ui_text import ui_text
from apps.payments.internal_balance import INTERNAL_BALANCE_PROVIDER_ID
from apps.payments.providers.registry import get_product_provider_buttons

from .models import (
    Category,
    HomepageCategorySection,
    Product,
    ProductCard,
    ProductInputField,
)
from .search_utils import (
    build_card_search_q,
    filter_cards_by_public_tag,
    tokenize_search,
)
from .sku_display import build_selected_sku_rows
from .visibility import listed_product_cards, listed_products, purchasable_product_cards
from .serializers import CategorySerializer, ProductCardSerializer, ProductSerializer


def _format_money_human(value) -> str:
    if value is None:
        return "0"
    amount = Decimal(str(value))
    if amount == amount.to_integral_value():
        return str(int(amount))
    return f"{amount:.2f}"


def _card_min_price(card: ProductCard):
    prices = []
    for product in card.products.all():
        if product.price is not None:
            prices.append(Decimal(str(product.price)))
    if not prices:
        return None
    return min(prices)


class _SafeTemplateMap(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _build_card_caption(card: ProductCard, template: str | None = None) -> str:
    tpl = (template or "{category}").strip() or "{category}"
    min_price = _card_min_price(card)
    ctx = _SafeTemplateMap(
        category=card.category.name if card.category_id else "",
        name=card.name,
        price=_format_money_human(min_price) if min_price is not None else "",
        buyers=str(card.unique_buyers_count),
        fulfillment=card.get_fulfillment_mode_display(),
    )
    try:
        return tpl.format_map(ctx)
    except Exception:
        return card.category.name if card.category_id else "Product"


def _attach_ui_caption(cards, template: str | None = None):
    for card in cards:
        card.ui_caption = _build_card_caption(card, template=template)
    return cards


class CategoryViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    queryset = Category.objects.filter(is_active=True).order_by("name")
    serializer_class = CategorySerializer
    lookup_field = "slug"


class ProductCardViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = ProductCardSerializer
    lookup_field = "slug"

    def get_queryset(self):
        base = (
            listed_product_cards()
            if self.action == "list"
            else purchasable_product_cards()
        )
        qs = (
            base.select_related("category", "default_product")
            .prefetch_related(
                Prefetch(
                    "products",
                    queryset=listed_products().order_by("id")
                    if self.action == "list"
                    else Product.objects.filter(is_active=True, is_hidden=False).order_by(
                        "id"
                    ),
                ),
                Prefetch(
                    "input_fields",
                    queryset=ProductInputField.objects.filter(is_active=True).order_by(
                        "sort_order", "id"
                    ),
                ),
            )
            .order_by("-created_at")
        )
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            tokens = tokenize_search(q)
            cq = build_card_search_q(tokens)
            if cq:
                qs = qs.filter(cq)
        tag = (self.request.query_params.get("tag") or "").strip()
        if tag:
            qs = filter_cards_by_public_tag(qs, tag)
        return qs


class ProductViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = ProductSerializer
    lookup_field = "id"

    def get_queryset(self):
        queryset = listed_products().select_related(
            "product_card", "product_card__category"
        )

        category_slug = self.request.query_params.get("category")
        featured = self.request.query_params.get("featured")
        product_card_slug = self.request.query_params.get("product_card")

        if category_slug:
            queryset = queryset.filter(product_card__category__slug=category_slug)

        if featured in {"1", "true", "True"}:
            queryset = queryset.filter(product_card__is_featured=True)

        if product_card_slug:
            queryset = queryset.filter(product_card__slug=product_card_slug)

        q = (self.request.query_params.get("q") or "").strip()
        if q:
            tokens = tokenize_search(q)
            cq = build_card_search_q(tokens)
            if cq:
                matching_cards = (
                    listed_product_cards().filter(cq).values_list("id", flat=True)
                )
                queryset = queryset.filter(product_card_id__in=matching_cards)

        tag = (self.request.query_params.get("tag") or "").strip()
        if tag:
            card_qs = filter_cards_by_public_tag(listed_product_cards(), tag)
            queryset = queryset.filter(
                product_card_id__in=card_qs.values_list("id", flat=True)
            )

        return queryset.order_by("id")


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def catalog_home_view(request):
    categories = Category.objects.filter(is_active=True).order_by("name")
    cards_qs = listed_product_cards().select_related(
        "category", "default_product"
    ).prefetch_related(
        Prefetch(
            "products",
            queryset=listed_products().order_by("id"),
        )
    )

    search_query = (request.GET.get("q") or "").strip()
    filter_tag = (request.GET.get("tag") or "").strip()
    feed = (request.GET.get("feed") or "popular").strip().lower()
    if feed not in {"popular", "new"}:
        feed = "popular"

    if search_query:
        tokens = tokenize_search(search_query)
        sq = build_card_search_q(tokens)
        if sq:
            cards_qs = cards_qs.filter(sq)
    if filter_tag:
        cards_qs = filter_cards_by_public_tag(cards_qs, filter_tag)

    if feed == "new":
        cards = cards_qs.order_by("-updated_at", "-created_at")
    else:
        cards = (
            cards_qs.filter(exclude_from_popular=False)
            .annotate(
                purchase_count=Coalesce(
                    Sum(
                        "products__order_items__quantity",
                        filter=Q(
                            products__order_items__order__status__in=[
                                Order.Status.PAID,
                                Order.Status.COMPLETED,
                            ]
                        ),
                    ),
                    Value(0),
                )
            )
            .order_by("-unique_buyers_count", "-purchase_count", "-created_at")
        )

    page_size = 36 if (search_query or filter_tag) else 12
    page_number = request.GET.get("page") or 1
    paginator = Paginator(cards, page_size)
    page_obj = paginator.get_page(page_number)
    next_page = page_obj.next_page_number() if page_obj.has_next() else None

    if _is_htmx(request) and request.GET.get("chunk") == "pinned":
        section_id = request.GET.get("section_id")
        section = get_object_or_404(
            HomepageCategorySection.objects.select_related("category"),
            id=section_id,
            is_active=True,
        )
        section_page_size = max(1, int(section.items_limit))
        section_page_number = request.GET.get("page") or 1
        section_cards_qs = cards_qs.filter(category=section.category).order_by(
            "-updated_at", "-created_at"
        )
        section_paginator = Paginator(section_cards_qs, section_page_size)
        section_page_obj = section_paginator.get_page(section_page_number)
        section_next_page = (
            section_page_obj.next_page_number() if section_page_obj.has_next() else None
        )
        pinned_context = {
            "section": section,
            "cards": _attach_ui_caption(
                section_page_obj.object_list, template=section.card_caption_template
            ),
            "next_page": section_next_page,
            "search_query": search_query,
            "filter_tag": filter_tag,
        }
        return render(
            request, "catalog/partials/pinned_section_chunk.html", pinned_context
        )

    pinned_category_rows = []
    if not search_query and not filter_tag:
        pinned_sections = (
            HomepageCategorySection.objects.filter(is_active=True)
            .select_related("category")
            .order_by("sort_order", "id")
        )
        for section in pinned_sections:
            section_page_size = max(1, int(section.items_limit))
            section_cards_qs = cards_qs.filter(category=section.category).order_by(
                "-updated_at", "-created_at"
            )
            section_paginator = Paginator(section_cards_qs, section_page_size)
            section_page_obj = section_paginator.get_page(1)
            section_cards = list(section_page_obj.object_list)
            if not section_cards:
                continue
            section_cards = _attach_ui_caption(
                section_cards, template=section.card_caption_template
            )
            pinned_category_rows.append(
                {
                    "section": section,
                    "title": section.title or section.category.name,
                    "cards": section_cards,
                    "next_page": section_page_obj.next_page_number()
                    if section_page_obj.has_next()
                    else None,
                }
            )

    context = {
        "categories": categories,
        "cards": _attach_ui_caption(page_obj.object_list, template="{category}"),
        "pinned_category_rows": pinned_category_rows,
        "search_query": search_query,
        "filter_tag": filter_tag,
        "active_feed": feed,
        "page_size": page_size,
        "current_page": page_obj.number,
        "next_page": next_page,
        "is_htmx": _is_htmx(request),
    }

    if _is_htmx(request) and request.GET.get("chunk") == "recommended":
        return render(request, "catalog/partials/recommended_cards_chunk.html", context)
    if _is_htmx(request):
        return render(request, "catalog/partials/home_content.html", context)
    return render(request, "catalog/home.html", context)


def product_detail_view(request, slug: str):
    card = get_object_or_404(
        purchasable_product_cards()
        .select_related("category", "default_product")
        .prefetch_related(
            Prefetch(
                "products",
                queryset=Product.objects.filter(is_active=True, is_hidden=False).order_by(
                    "id"
                ),
            ),
            Prefetch(
                "input_fields",
                queryset=ProductInputField.objects.filter(is_active=True).order_by(
                    "sort_order", "id"
                ),
            ),
        ),
        slug=slug,
    )

    products = list(card.products.all())
    selected_product_id = request.GET.get("product")
    selected_product = None
    if selected_product_id:
        selected_product = next(
            (p for p in products if str(p.id) == str(selected_product_id)), None
        )
    if not selected_product:
        selected_product = card.default_product if card.default_product_id else None
    if not selected_product and products:
        selected_product = products[0]

    ui_labels_default = ui_text()["catalog"]["product_labels_default"]
    ui_labels = {**ui_labels_default, **(card.ui_labels or {})}
    if card.fulfillment_mode == ProductCard.FulfillmentMode.INSTANT:
        fulfillment_label = ui_labels["fulfillment_instant"]
    elif card.fulfillment_mode == ProductCard.FulfillmentMode.MANUAL:
        fulfillment_label = ui_labels["fulfillment_manual"]
    else:
        fulfillment_label = card.fulfillment_mode

    products_json = json.dumps(
        [
            {
                "id": product.id,
                "price": str(product.price),
                "old_price": str(product.old_price) if product.old_price else None,
                "stock_count": product.stock_count,
                "sort_order": int(product.sort_order or 0),
                "attributes": product.attributes,
                "image_url": product.image_url or "",
            }
            for product in products
        ],
        cls=DjangoJSONEncoder,
    )

    products_for_js = [
        {
            "id": product.id,
            "price": str(product.price),
            "old_price": str(product.old_price) if product.old_price else None,
            "stock_count": product.stock_count,
            "sort_order": int(product.sort_order or 0),
            "attributes": product.attributes or {},
            "image_url": product.image_url or "",
            "selection_rows": build_selected_sku_rows(
                product_id=product.id,
                price=product.price,
                attributes=product.attributes or {},
                selector_axes=card.selector_axes or [],
                ui_labels=ui_labels,
            ),
        }
        for product in products
    ]

    card_hero_fallback = ""
    if card.image_url:
        card_hero_fallback = card.image_url
    elif card.image:
        card_hero_fallback = card.image.url

    product_payment_methods = [
        {
            "id": INTERNAL_BALANCE_PROVIDER_ID,
            "label": "Balance",
            "sort_order": 0,
            "min_product_amount": "0",
        }
    ]
    product_payment_methods.extend(get_product_provider_buttons())

    input_fields_validation = [
        {
            "key": field.key,
            "field_type": field.field_type,
            "is_required": bool(field.is_required),
            "min_value": str(field.min_value) if field.min_value is not None else None,
            "max_value": str(field.max_value) if field.max_value is not None else None,
            "regex": (field.regex or "").strip(),
            "label": field.label,
            "field_dom_id": f"pd-field-{field.id}",
        }
        for field in card.input_fields.all()
    ]
    if card.include_telegram_handle_field:
        input_fields_validation.append(
            {
                "key": "telegram_handle",
                "field_type": "text",
                "is_required": False,
                "min_value": None,
                "max_value": None,
                "regex": "",
                "label": "Telegram for contact",
                "field_dom_id": "pd-field-telegram-handle",
                "max_length": 64,
            }
        )

    context = {
        "card": card,
        "selected_product": selected_product,
        "products": products,
        "products_json": products_json,
        "products_for_js": products_for_js,
        "selector_axes_for_js": list(card.selector_axes or []),
        "selector_value_order_for_js": card.selector_value_order or {},
        "card_hero_fallback": card_hero_fallback,
        "ui_labels": ui_labels,
        "fulfillment_label": fulfillment_label,
        "input_fields": card.input_fields.all(),
        "input_fields_validation": input_fields_validation,
        "payment_methods_for_js": product_payment_methods,
        "quantity_selection_enabled": bool(card.quantity_selection_enabled),
        "min_order_quantity": int(card.min_order_quantity or 1),
        "max_order_quantity": int(card.max_order_quantity or 1),
        "default_order_quantity": int(card.default_order_quantity or 1),
        "show_telegram_handle_field": bool(card.include_telegram_handle_field),
        "telegram_handle_prefill": (
            str(getattr(getattr(request.user, "account_profile", None), "telegram_handle", "") or "").strip()
            if request.user.is_authenticated
            else ""
        ),
        "search_query": "",
        "is_htmx": _is_htmx(request),
    }
    if _is_htmx(request):
        return render(request, "catalog/partials/product_detail_content.html", context)
    return render(request, "catalog/product_detail.html", context)
