import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.orders.models import Order

User = get_user_model()


def _token(*, order_public_id: int, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        str(int(order_public_id)).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()[:12]


@override_settings(BOT_INTERNAL_API_KEY="test-bot-secret")
class ManualOrderTelegramCompleteViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="op",
            email="op@example.com",
            password="x",
        )
        self.order = Order.objects.create(
            user=self.user,
            status=Order.Status.MANUAL_PENDING,
            total=Decimal("100.00"),
            currency="USD",
        )

    def _post(self, payload: dict, *, api_key: str = "test-bot-secret"):
        return self.client.post(
            reverse("bot-manual-order-complete"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_API_KEY=api_key,
        )

    def test_401_without_key(self):
        resp = self.client.post(
            reverse("bot-manual-order-complete"),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_403_bad_token(self):
        resp = self._post(
            {
                "order_public_id": self.order.public_id,
                "callback_token": "deadbeef0000",
            }
        )
        self.assertEqual(resp.status_code, 403)

    @patch("apps.orders.services._queue_order_completed_email")
    def test_completes_manual_pending(self, _mock_email):
        tok = _token(order_public_id=self.order.public_id, secret="test-bot-secret")
        resp = self._post(
            {"order_public_id": self.order.public_id, "callback_token": tok}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.COMPLETED)

    @patch("apps.orders.services._queue_order_completed_email")
    def test_idempotent_when_already_completed(self, _mock_email):
        tok = _token(order_public_id=self.order.public_id, secret="test-bot-secret")
        first = self._post(
            {"order_public_id": self.order.public_id, "callback_token": tok}
        )
        self.assertEqual(first.status_code, 200)
        second = self._post(
            {"order_public_id": self.order.public_id, "callback_token": tok}
        )
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json().get("already_completed"))
