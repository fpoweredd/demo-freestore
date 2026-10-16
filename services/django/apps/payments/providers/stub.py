from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError

from .base import BasePaymentProvider


class StubPaymentProvider(BasePaymentProvider):
    """UI stub — button visible, checkout not wired yet."""

    name = "stub"

    def create_invoice(
        self,
        *,
        reference_id: int,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
        order_description: str = "",
        success_url: str | None = None,
        cancel_url: str | None = None,
    ) -> dict[str, Any]:
        raise ValidationError(
            {"provider": "This payment method is not available yet (stub)."}
        )

    def verify_webhook(
        self,
        *,
        raw_body: bytes,
        signature_header: str | None,
        webhook_timestamp: str | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        return False, None

    def parse_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider_payment_id": "",
            "provider_status": "stub",
            "is_success": False,
        }

    @property
    def min_amount(self) -> Decimal:
        return Decimal("1.00")

    @property
    def supported_currencies(self) -> list[str]:
        return ["USD"]
