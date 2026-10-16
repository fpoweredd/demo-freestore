from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Category, Product, ProductCard
from apps.catalog.visibility import listed_product_cards, purchasable_product_cards


class HiddenCardVisibilityTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Test", slug="test", is_active=True)
        self.hidden_card = ProductCard.objects.create(
            category=self.category,
            name="Stealth Product",
            slug="stealth-product",
            is_active=True,
            is_hidden=True,
        )
        self.public_card = ProductCard.objects.create(
            category=self.category,
            name="Public Product",
            slug="public-product",
            is_active=True,
            is_hidden=False,
        )
        Product.objects.create(
            product_card=self.hidden_card,
            price="100.00",
            stock_count=1,
            is_active=True,
        )
        Product.objects.create(
            product_card=self.public_card,
            price="50.00",
            stock_count=1,
            is_active=True,
        )

    def test_hidden_card_excluded_from_listed_queryset(self):
        slugs = set(listed_product_cards().values_list("slug", flat=True))
        self.assertIn("public-product", slugs)
        self.assertNotIn("stealth-product", slugs)

    def test_hidden_card_available_for_direct_link_queryset(self):
        slugs = set(purchasable_product_cards().values_list("slug", flat=True))
        self.assertIn("stealth-product", slugs)

    def test_product_detail_allows_hidden_active_card(self):
        url = reverse("catalog:product-detail", kwargs={"slug": "stealth-product"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_home_search_does_not_surface_hidden_card(self):
        response = self.client.get(reverse("catalog:home"), {"q": "Stealth"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "stealth-product")
