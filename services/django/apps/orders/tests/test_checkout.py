from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import AccountProfile
from apps.catalog.models import Category, DigitalItem, Product, ProductCard
from apps.orders.models import Order, OrderItemDigitalItem, OrderStatusLog, PreOrder
from apps.orders.services import (
    create_order_from_quote,
    fulfill_waiting_stock_orders_for_product,
    process_paid_order,
)
from apps.payments.internal_balance import INTERNAL_BALANCE_PROVIDER_ID

User = get_user_model()


class CheckoutFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.category = Category.objects.create(name="Games", slug="games")
        self.card = ProductCard.objects.create(
            category=self.category,
            name="Steam Gift",
            slug="steam-gift",
            fulfillment_mode=ProductCard.FulfillmentMode.INSTANT,
        )
        self.product = Product.objects.create(
            product_card=self.card,
            price=Decimal("10.00"),
            stock_count=2,
            is_active=True,
        )
        DigitalItem.objects.create(product=self.product, payload_encrypted="enc-1")
        DigitalItem.objects.create(product=self.product, payload_encrypted="enc-2")
        self.user = User.objects.create_user(
            username="buyer",
            email="buyer@example.com",
            password="strongpass1",
        )
        AccountProfile.objects.create(user=self.user, balance=Decimal("5.00"))

    @patch("apps.orders.services.get_provider")
    @patch("apps.orders.services.get_product_provider_buttons")
    def test_quote_returns_checkout_decision_tree(
        self, mock_get_product_provider_buttons, mock_get_provider
    ):
        mock_get_product_provider_buttons.return_value = [
            {"id": "nowpayments", "label": "NowPayments", "min_product_amount": "0.00"}
        ]
        provider = Mock()
        provider.min_amount = Decimal("100.00")
        mock_get_provider.return_value = provider
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/v1/orders/quote/",
            {
                "currency": "RUB",
                "items": [{"product_id": self.product.id, "quantity": 1}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total"], "10.00")
        self.assertEqual(
            response.data["checkout"]["recommended_action"], "wallet_topup_required"
        )
        self.assertEqual(response.data["checkout"]["wallet_balance"], "5.00")
        methods = {
            row["id"]: row for row in response.data["checkout"]["payment_methods"]
        }
        self.assertIn(INTERNAL_BALANCE_PROVIDER_ID, methods)
        self.assertIn("nowpayments", methods)
        self.assertFalse(methods["nowpayments"]["direct_pay_available"])
        self.assertEqual(methods["nowpayments"]["suggested_topup_amount"], "100.00")

    def test_create_order_is_idempotent_and_reserves_digital_items(self):
        # Reservation is optional and disabled by default; enable for this test.
        self.card.use_reservations = True
        self.card.save(update_fields=["use_reservations"])

        order = create_order_from_quote(
            items_data=[{"product_id": self.product.id, "quantity": 1}],
            currency="USD",
            user=self.user,
            idempotency_key="checkout-1",
        )
        same_order = create_order_from_quote(
            items_data=[{"product_id": self.product.id, "quantity": 1}],
            currency="USD",
            user=self.user,
            idempotency_key="checkout-1",
        )

        self.product.refresh_from_db()
        self.assertEqual(order.pk, same_order.pk)
        self.assertEqual(self.product.stock_count, 1)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItemDigitalItem.objects.count(), 1)
        self.assertTrue(
            OrderStatusLog.objects.filter(
                order=order,
                to_status=Order.Status.AWAITING_PAYMENT,
            ).exists()
        )

    def test_process_paid_order_consumes_reserved_items_and_logs_statuses(self):
        order = create_order_from_quote(
            items_data=[{"product_id": self.product.id, "quantity": 1}],
            currency="USD",
            user=self.user,
            idempotency_key="checkout-2",
        )

        process_paid_order(order)

        order.refresh_from_db()
        reserved_link = OrderItemDigitalItem.objects.select_related(
            "digital_item"
        ).get()
        reserved_link.digital_item.refresh_from_db()
        self.assertTrue(reserved_link.digital_item.is_used)
        self.assertEqual(order.status, Order.Status.COMPLETED)
        self.assertTrue(
            OrderStatusLog.objects.filter(
                order=order, to_status=Order.Status.PAID
            ).exists()
        )
        self.assertTrue(
            OrderStatusLog.objects.filter(
                order=order, to_status=Order.Status.COMPLETED
            ).exists()
        )

    def test_preorder_model_created_and_fulfilled_on_stock_arrival(self):
        # No instant stock; preorder should be created and later fulfilled.
        DigitalItem.objects.all().delete()
        self.product.stock_count = 0
        self.product.save(update_fields=["stock_count"])

        order = create_order_from_quote(
            items_data=[{"product_id": self.product.id, "quantity": 1}],
            currency="USD",
            user=self.user,
            idempotency_key="checkout-pre-1",
        )
        self.assertEqual(PreOrder.objects.count(), 1)
        preorder = PreOrder.objects.get(order=order)
        self.assertEqual(preorder.status, PreOrder.Status.PENDING)

        process_paid_order(order)
        order.refresh_from_db()
        preorder.refresh_from_db()
        self.assertEqual(order.status, Order.Status.WAITING_STOCK)
        self.assertEqual(preorder.status, PreOrder.Status.PAID)

        DigitalItem.objects.create(product=self.product, payload_encrypted="enc-new-1")
        completed = fulfill_waiting_stock_orders_for_product(product=self.product)
        self.assertEqual(completed, 1)

        order.refresh_from_db()
        preorder.refresh_from_db()
        self.assertEqual(order.status, Order.Status.COMPLETED)
        self.assertEqual(preorder.status, PreOrder.Status.FULFILLED)

    def test_preorder_auto_fulfilled_when_single_digital_item_created(self):
        DigitalItem.objects.all().delete()
        self.product.stock_count = 0
        self.product.save(update_fields=["stock_count"])

        order = create_order_from_quote(
            items_data=[{"product_id": self.product.id, "quantity": 1}],
            currency="USD",
            user=self.user,
            idempotency_key="checkout-pre-auto-1",
        )
        process_paid_order(order)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.WAITING_STOCK)

        with self.captureOnCommitCallbacks(execute=True):
            DigitalItem.objects.create(
                product=self.product, payload_encrypted="enc-new-signal-1"
            )

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.COMPLETED)

    def test_partial_fulfillment_then_complete_after_restock(self):
        self.card.quantity_selection_enabled = True
        self.card.min_order_quantity = 1
        self.card.max_order_quantity = 5
        self.card.default_order_quantity = 1
        self.card.save(
            update_fields=[
                "quantity_selection_enabled",
                "min_order_quantity",
                "max_order_quantity",
                "default_order_quantity",
            ]
        )
        DigitalItem.objects.all().delete()
        self.product.stock_count = 0
        self.product.save(update_fields=["stock_count"])
        DigitalItem.objects.create(
            product=self.product, payload_encrypted="enc-only-one"
        )
        self.product.stock_count = 1
        self.product.save(update_fields=["stock_count"])

        order = create_order_from_quote(
            items_data=[{"product_id": self.product.id, "quantity": 2}],
            currency="USD",
            user=self.user,
            idempotency_key="checkout-partial-1",
        )
        process_paid_order(order)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PARTIALLY_FULFILLED)
        order_item = order.items.get()
        self.assertEqual(order_item.reserved_digital_items.count(), 1)

        DigitalItem.objects.create(product=self.product, payload_encrypted="enc-second")
        completed = fulfill_waiting_stock_orders_for_product(product=self.product)
        self.assertEqual(completed, 1)

        order.refresh_from_db()
        order_item.refresh_from_db()
        self.assertEqual(order_item.reserved_digital_items.count(), 2)
        self.assertEqual(order.status, Order.Status.COMPLETED)
