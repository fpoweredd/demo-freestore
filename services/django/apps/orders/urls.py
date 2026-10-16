from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ManualDispatchLogViewSet,
    OrderQuoteAPIView,
    OrderViewSet,
    PreOrderStockUploadRequestAPIView,
)

app_name = "orders"

router = DefaultRouter()
router.register("orders", OrderViewSet, basename="order")
router.register("manual-dispatch-logs", ManualDispatchLogViewSet, basename="manual-dispatch-log")

urlpatterns = [
    path("orders/quote/", OrderQuoteAPIView.as_view(), name="order-quote"),
    path(
        "preorders/<int:public_id>/request-stock-upload/",
        PreOrderStockUploadRequestAPIView.as_view(),
        name="preorder-request-stock-upload",
    ),
    *router.urls,
]
