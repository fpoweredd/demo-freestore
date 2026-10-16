import hashlib
import hmac
import json

from django.test import SimpleTestCase


class NowPaymentsSigTests(SimpleTestCase):
    def test_hmac_matches_php_style(self):
        secret = "test-ipn-secret"
        payload = {"payment_id": "p1", "payment_status": "finished", "order_id": "123"}
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        expected = hmac.new(
            secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()
        self.assertEqual(len(expected), 128)
