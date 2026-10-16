"""Storefront visibility rules for ProductCard / Product."""

from __future__ import annotations

from django.db.models import QuerySet

from .models import Product, ProductCard


def listed_product_cards() -> QuerySet[ProductCard]:
    """Catalog, search, homepage, API list — hidden cards excluded."""
    return ProductCard.objects.filter(is_active=True, is_hidden=False)


def listed_products() -> QuerySet[Product]:
    """Visible SKU variants inside listings and selectors on public cards."""
    return Product.objects.filter(
        is_active=True,
        is_hidden=False,
        product_card__is_active=True,
        product_card__is_hidden=False,
    )


def purchasable_product_cards() -> QuerySet[ProductCard]:
    """Direct link + checkout — hidden but active cards allowed."""
    return ProductCard.objects.filter(is_active=True)


def purchasable_products() -> QuerySet[Product]:
    """Checkout / quote — allow SKUs on hidden cards; variant-level hidden still excluded."""
    return Product.objects.filter(
        is_active=True,
        is_hidden=False,
        product_card__is_active=True,
    )
