import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import AccountProfile
from apps.orders.models import Order
from apps.payments.internal_balance import INTERNAL_BALANCE_PROVIDER_ID
from apps.payments.models import (
    BalanceTopUp,
    Payment,
    PaymentProviderSettings,
    PaymentRefund,
    WalletTransaction,
)
from apps.payments.providers.enot import EnotProvider, _enot_webhook_canonical_json
from apps.payments.providers.rollypay import RollyPayProvider
from apps.payments.services import (
    apply_enot_webhook,
    apply_nowpayments_webhook,
    apply_rollypay_webhook,
    create_wallet_transaction,
    init_balance_topup_payment,
    init_payment_for_order,
)

User = get_user_model()


class PaymentsFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="buyer",
            email="buyer@example.com",
            password="strongpass1",
        )
        self.profile = AccountProfile.objects.create(
            user=self.user, balance=Decimal("0.00")
        )

    def test_init_payment_for_order_with_wallet_debits_once_and_completes_order(self):
        self.profile.balance = Decimal("250.00")
        self.profile.save(update_fields=["balance"])
        order = Order.objects.create(
            user=self.user,
            status=Order.Status.AWAITING_PAYMENT,
            total=Decimal("149.00"),
            currency="USD",
        )

        payment = init_payment_for_order(
            order_public_id=order.public_id,
            provider_name=INTERNAL_BALANCE_PROVIDER_ID,
            user=self.user,
            guest_email="",
        )

        self.profile.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(payment.provider, INTERNAL_BALANCE_PROVIDER_ID)
        self.assertEqual(self.profile.balance, Decimal("101.00"))
        self.assertEqual(WalletTransaction.objects.count(), 1)
        self.assertEqual(
            WalletTransaction.objects.get().kind, WalletTransaction.Kind.ORDER_DEBIT
        )
        self.assertNotEqual(order.status, Order.Status.AWAITING_PAYMENT)

    @patch("apps.payments.services.get_provider")
    @patch("apps.payments.providers.registry.get_enabled_provider_ids")
    def test_init_balance_topup_payment_creates_processing_payment(
        self,
        mock_get_enabled_provider_ids,
        mock_get_provider,
    ):
        PaymentProviderSettings.objects.update_or_create(
            provider_id="nowpayments",
            defaults={
                "is_enabled": True,
                "balance_topup_min_amount": Decimal("10.00"),
                "balance_topup_max_amount": Decimal("1000.00"),
            },
        )
        mock_get_enabled_provider_ids.return_value = ["nowpayments"]
        mock_provider = Mock()
        mock_provider.min_amount = Decimal("1.00")
        mock_provider.create_invoice.return_value = {
            "invoice_url": "https://example.com/invoice/1",
            "provider_payment_id": "np-1",
        }
        mock_get_provider.return_value = mock_provider

        payment = init_balance_topup_payment(
            user=self.user,
            amount=Decimal("100.00"),
            currency="USD",
            provider_name="nowpayments",
        )

        self.assertEqual(payment.status, Payment.Status.PROCESSING)
        self.assertEqual(payment.invoice_url, "https://example.com/invoice/1")
        self.assertTrue(
            BalanceTopUp.objects.filter(pk=payment.balance_top_up_id).exists()
        )

    def test_apply_nowpayments_webhook_is_idempotent_for_topup_credit(self):
        topup = BalanceTopUp.objects.create(
            user=self.user,
            amount=Decimal("100.00"),
            currency="USD",
            status=BalanceTopUp.Status.PENDING,
        )
        payment = Payment.objects.create(
            balance_top_up=topup,
            provider="nowpayments",
            provider_payment_id="np-topup-1",
            amount=Decimal("100.00"),
            currency="USD",
            status=Payment.Status.PROCESSING,
        )
        payload = {
            "id": "np-topup-1",
            "payment_id": "np-topup-1",
            "payment_status": "finished",
            "order_id": str(topup.public_id),
        }

        code, _ = apply_nowpayments_webhook(payload=payload, signature_valid=True)
        code_dup, _ = apply_nowpayments_webhook(payload=payload, signature_valid=True)

        self.profile.refresh_from_db()
        topup.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(code, 200)
        self.assertEqual(code_dup, 200)
        self.assertEqual(self.profile.balance, Decimal("100.00"))
        self.assertEqual(topup.status, BalanceTopUp.Status.COMPLETED)
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(
            WalletTransaction.objects.filter(
                kind=WalletTransaction.Kind.TOPUP_CREDIT
            ).count(),
            1,
        )

    def test_apply_nowpayments_refund_creates_payment_refund_and_wallet_debit(self):
        topup = BalanceTopUp.objects.create(
            user=self.user,
            amount=Decimal("80.00"),
            currency="USD",
            status=BalanceTopUp.Status.COMPLETED,
        )
        payment = Payment.objects.create(
            balance_top_up=topup,
            provider="nowpayments",
            provider_payment_id="np-topup-2",
            amount=Decimal("80.00"),
            currency="USD",
            status=Payment.Status.SUCCEEDED,
            provider_status="finished",
        )
        create_wallet_transaction(
            user_id=self.user.pk,
            kind=WalletTransaction.Kind.TOPUP_CREDIT,
            source_type=WalletTransaction.SourceType.PAYMENT,
            source_id=str(payment.pk),
            amount=Decimal("80.00"),
            currency="USD",
            description="Balance top-up",
            metadata={"payment_id": str(payment.pk)},
        )

        payload = {
            "id": "np-topup-2",
            "payment_id": "np-topup-2",
            "payment_status": "refunded",
            "order_id": str(topup.public_id),
            "refund_id": "refund-1",
        }

        code, _ = apply_nowpayments_webhook(payload=payload, signature_valid=True)

        self.profile.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(code, 200)
        self.assertEqual(payment.status, Payment.Status.REFUNDED)
        self.assertEqual(self.profile.balance, Decimal("0.00"))
        self.assertTrue(
            PaymentRefund.objects.filter(
                payment=payment, provider_refund_id="refund-1"
            ).exists()
        )
        self.assertEqual(
            WalletTransaction.objects.filter(
                kind=WalletTransaction.Kind.CHARGEBACK_DEBIT
            ).count(),
            1,
        )

    def test_apply_rollypay_webhook_topup_success_idempotent(self):
        topup = BalanceTopUp.objects.create(
            user=self.user,
            amount=Decimal("50.00"),
            currency="USD",
            status=BalanceTopUp.Status.PENDING,
        )
        payment = Payment.objects.create(
            balance_top_up=topup,
            provider="rollypay",
            provider_payment_id="pay_test_1",
            amount=Decimal("50.00"),
            currency="USD",
            status=Payment.Status.PROCESSING,
        )
        payload = {
            "event_type": "payment.paid",
            "payment_id": "pay_test_1",
            "order_id": str(topup.public_id),
            "status": "paid",
            "amount": "50.00",
            "currency": "RUB",
        }

        code1, _ = apply_rollypay_webhook(payload=payload, signature_valid=True)
        code2, _ = apply_rollypay_webhook(payload=payload, signature_valid=True)

        self.profile.refresh_from_db()
        topup.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(code1, 200)
        self.assertEqual(code2, 200)
        self.assertEqual(self.profile.balance, Decimal("50.00"))
        self.assertEqual(topup.status, BalanceTopUp.Status.COMPLETED)
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)

    @override_settings(
        ROLLYPAY_API_KEY="k",
        ROLLYPAY_SIGNING_SECRET="signing_test_secret",
    )
    def test_rollypay_verify_webhook_hmac(self):
        body = b'{"event_type":"payment.paid","payment_id":"pay_x","order_id":"1","status":"paid"}'
        ts = "1700000000"
        expected = hmac.new(
            b"signing_test_secret",
            (ts + "." + body.decode("utf-8")).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        p = RollyPayProvider()
        ok, parsed = p.verify_webhook(
            raw_body=body, signature_header=expected, webhook_timestamp=ts
        )
        self.assertTrue(ok)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed.get("payment_id"), "pay_x")

    @override_settings(
        ENOT_SHOP_ID="shop",
        ENOT_API_KEY="api",
        ENOT_WEBHOOK_SECRET="example",
    )
    def test_enot_verify_webhook_hmac(self):
        hook = {
            "amount": "100.00",
            "credited": "95.50",
            "custom_fields": {"user": 1},
            "invoice_id": "a3e9ff6f-c5c1-3bcd-854e-4bc995b1ae7a",
            "order_id": "c78d8fe9-ab44-3f21-a37a-ce4ca269cb47",
            "pay_service": "card",
            "pay_time": "2023-04-06 16:27:59",
            "payer_details": "553691******1279",
            "status": "success",
            "type": 1,
        }
        # Official Enot doc test vector (secret "example").
        doc_signature = (
            "e582b14dd13f8111711e3cb66a982fd7bff28a0ddece8bde14a34a5bb4449136"
        )
        body = json.dumps(hook, separators=(",", ":")).encode("utf-8")

        provider = EnotProvider()
        ok, parsed = provider.verify_webhook(
            raw_body=body, signature_header=doc_signature
        )
        self.assertTrue(ok)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed.get("invoice_id"), hook["invoice_id"])

    def test_enot_webhook_fail_sends_payment_error_for_order(self):
        order = Order.objects.create(
            user=self.user,
            status=Order.Status.AWAITING_PAYMENT,
            total=Decimal("100.00"),
            currency="USD",
        )
        payment = Payment.objects.create(
            order=order,
            provider="enot",
            amount=order.total,
            currency=order.currency,
            status=Payment.Status.PROCESSING,
            provider_payment_id="inv-fail-1",
            idempotency_key="enot-fail-1",
        )
        payload = {
            "invoice_id": "inv-fail-1",
            "order_id": str(order.public_id),
            "status": "fail",
            "amount": "100.00",
            "currency": "RUB",
            "type": 1,
            "code": 32,
        }
        with patch(
            "apps.payments.services.post_payment_error_notify"
        ) as notify_mock:
            code, updated = apply_enot_webhook(
                payload=payload, signature_valid=True
            )
        self.assertEqual(code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        notify_mock.assert_called()
        call_payload = notify_mock.call_args[0][0]
        self.assertEqual(call_payload.get("error_code"), "payment_failed")

    def test_enot_webhook_expired_does_not_send_payment_failed_alert(self):
        order = Order.objects.create(
            user=self.user,
            status=Order.Status.AWAITING_PAYMENT,
            total=Decimal("50.00"),
            currency="USD",
        )
        payment = Payment.objects.create(
            order=order,
            provider="enot",
            amount=order.total,
            currency=order.currency,
            status=Payment.Status.PROCESSING,
            provider_payment_id="inv-exp-1",
            idempotency_key="enot-exp-1",
        )
        payload = {
            "invoice_id": "inv-exp-1",
            "order_id": str(order.public_id),
            "status": "expired",
            "amount": "50.00",
            "currency": "RUB",
            "type": 1,
            "code": 31,
        }
        with patch(
            "apps.payments.services.post_payment_error_notify"
        ) as notify_mock:
            apply_enot_webhook(payload=payload, signature_valid=True)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.EXPIRED)
        for call in notify_mock.call_args_list:
            payload_sent = call[0][0]
            self.assertNotEqual(payload_sent.get("error_code"), "payment_failed")

    def test_wallet_transactions_api_returns_real_rows(self):
        create_wallet_transaction(
            user_id=self.user.pk,
            kind=WalletTransaction.Kind.MANUAL_ADJUSTMENT,
            source_type=WalletTransaction.SourceType.MANUAL,
            source_id="manual-1",
            amount=Decimal("15.00"),
            currency="USD",
            description="Manual bonus",
        )
        self.client.force_authenticate(user=self.user)

        response = self.client.get(reverse("payment-wallet-transactions"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["entries"]), 1)
        self.assertEqual(
            response.data["entries"][0]["kind"],
            WalletTransaction.Kind.MANUAL_ADJUSTMENT,
        )
