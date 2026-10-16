from django.urls import path
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter

from .views import (
    CategoryViewSet,
    ProductCardViewSet,
    ProductViewSet,
    catalog_home_view,
    product_detail_view,
)

app_name = "catalog"

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("product-cards", ProductCardViewSet, basename="product-card")
router.register("products", ProductViewSet, basename="product")

urlpatterns = [
    path("", catalog_home_view, name="home"),
    path("catalog/", catalog_home_view, name="catalog"),
    path("p/<slug:slug>/", product_detail_view, name="product-detail"),
    path(
        "catalog/<slug:slug>/",
        RedirectView.as_view(pattern_name="catalog:product-detail", permanent=True),
    ),
    path(
        "products/<slug:slug>/",
        RedirectView.as_view(pattern_name="catalog:product-detail", permanent=True),
    ),
    *router.urls,
]
