from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any


class BasePaymentProvider(ABC):
    """Payment provider abstraction (invoice + webhook verification)."""

    name: str = ""

    @abstractmethod
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
        """
        reference_id is sent to the provider as client order id (Order.public_id or BalanceTopUp.public_id).
        Returns dict with at least: invoice_url, provider_payment_id (optional).
        """

    @abstractmethod
    def verify_webhook(
        self,
        *,
        raw_body: bytes,
        signature_header: str | None,
        webhook_timestamp: str | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        """Return (ok, parsed_json). Optional webhook_timestamp for providers that sign timestamp+body."""

    @abstractmethod
    def parse_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize provider payload to:
          provider_payment_id: str
          provider_status: str (raw)
          is_success: bool
        """

    @property
    @abstractmethod
    def min_amount(self) -> Decimal:
        ...

    @property
    @abstractmethod
    def supported_currencies(self) -> list[str]:
        ...
