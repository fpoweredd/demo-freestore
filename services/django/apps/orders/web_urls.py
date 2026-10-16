from django.urls import path

from .views import (
    order_create_from_product_view,
    order_page_view,
    order_payment_partial_view,
    order_status_partial_view,
)

app_name = "orders-web"

urlpatterns = [
    path("orders/create/", order_create_from_product_view, name="order-create"),
    path("orders/<int:public_id>/", order_page_view, name="order-page"),
    path("orders/<int:public_id>/status/", order_status_partial_view, name="order-status-partial"),
    path("orders/<int:public_id>/payment/", order_payment_partial_view, name="order-payment-partial"),
]
