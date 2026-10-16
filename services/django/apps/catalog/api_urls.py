from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, ProductCardViewSet, ProductViewSet

app_name = "catalog-api"

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("product-cards", ProductCardViewSet, basename="product-card")
router.register("products", ProductViewSet, basename="product")

urlpatterns = router.urls
