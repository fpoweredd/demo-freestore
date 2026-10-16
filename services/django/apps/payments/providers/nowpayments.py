from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any

import httpx
from django.conf import settings
from loguru import logger

from .base import BasePaymentProvider


def _sorted_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class NowPaymentsProvider(BasePaymentProvider):
    """
    NOWPayments invoice + IPN (x-nowpayments-sig).
    Docs: sort JSON keys, HMAC-SHA512(sorted_json, ipn_secret) compare to header.
    """

    name = "nowpayments"

    def __init__(self) -> None:
        self.api_key = (getattr(settings, "NOWPAYMENTS_API_KEY_SECRET", "") or "").strip()
        self.ipn_secret = (getattr(settings, "NOWPAYMENTS_IPN_SECRET", "") or "").strip()
        self.base_url = (
            getattr(settings, "NOWPAYMENTS_BASE_URL", None) or "https://api.nowpayments.io/v1"
        ).rstrip("/")
        self._min_amount = Decimal(str(getattr(settings, "NOWPAYMENTS_MIN_AMOUNT_FIAT", "1.0")))
        raw_cur = getattr(settings, "NOWPAYMENTS_SUPPORTED_FIAT", ["rub", "usd", "eur"])
        if isinstance(raw_cur, str):
            self._currencies = [x.strip().lower() for x in raw_cur.split(",") if x.strip()]
        else:
            self._currencies = [str(x).strip().lower() for x in raw_cur]

    @property
    def min_amount(self) -> Decimal:
        return self._min_amount

    @property
    def supported_currencies(self) -> list[str]:
        return self._currencies

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
        if not self.api_key:
            raise RuntimeError("NOWPAYMENTS_API_KEY_SECRET is not configured")

        site = str(getattr(settings, "PUBLIC_SITE_URL", "http://127.0.0.1:8000")).rstrip("/")
        ipn_url = f"{site}/webhooks/nowpayments/"
        rel_ok = getattr(settings, "NOWPAYMENTS_DEFAULT_SUCCESS_REL_PATH", "/") or "/"
        rel_cancel = getattr(settings, "NOWPAYMENTS_DEFAULT_CANCEL_REL_PATH", "/") or "/"
        if not rel_ok.startswith("/"):
            rel_ok = "/" + rel_ok
        if not rel_cancel.startswith("/"):
            rel_cancel = "/" + rel_cancel
        default_success = f"{site}{rel_ok}"
        default_cancel = f"{site}{rel_cancel}"
        success_url = success_url or default_success
        cancel_url = cancel_url or default_cancel

        fiat = currency.lower()
        description = order_description.strip() or f"Payment {reference_id}"
        body = {
            "price_amount": str(amount),
            "price_currency": fiat,
            "order_id": str(reference_id),
            "order_description": description[:512],
            "ipn_callback_url": ipn_url,
            "success_url": success_url,
            "cancel_url": cancel_url,
        }

        headers = {"x-api-key": self.api_key, "Content-Type": "application/json"}
        url = f"{self.base_url}/invoice"
        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=45.0)
        except httpx.RequestError as exc:
            logger.exception("nowpayments_invoice_http_error")
            raise RuntimeError("NOWPayments request failed") from exc

        if resp.status_code >= 400:
            logger.error("nowpayments_invoice_bad_status {} body {}", resp.status_code, resp.text[:2000])
            raise RuntimeError(f"NOWPayments invoice error: HTTP {resp.status_code}")

        data = resp.json()
        invoice_url = data.get("invoice_url") or data.get("redirect_url") or ""
        ext_id = data.get("id")
        if ext_id is not None:
            ext_id = str(ext_id)
        return {
            "invoice_url": invoice_url,
            "provider_payment_id": ext_id,
            "raw": data,
        }

    def verify_webhook(
        self,
        *,
        raw_body: bytes,
        signature_header: str | None,
        webhook_timestamp: str | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        if not self.ipn_secret:
            logger.warning("NOWPAYMENTS_IPN_SECRET missing; webhook rejected")
            return False, None
        if not signature_header:
            return False, None
        try:
            raw_text = raw_body.decode("utf-8")
            payload = json.loads(raw_text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False, None
        if not isinstance(payload, dict):
            return False, None

        sig = signature_header.strip().lower()
        expected_sorted = hmac.new(
            self.ipn_secret.encode("utf-8"),
            _sorted_json(payload).encode("utf-8"),
            hashlib.sha512,
        ).hexdigest().lower()
        expected_raw = hmac.new(
            self.ipn_secret.encode("utf-8"),
            raw_text.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest().lower()

        ok = hmac.compare_digest(expected_sorted, sig) or hmac.compare_digest(
            expected_raw, sig
        )
        if not ok:
            logger.warning(
                "nowpayments_webhook_signature_mismatch payload_keys={} header_len={}",
                list(payload.keys()),
                len(sig),
            )
        return ok, payload

    def parse_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        payment_id = payload.get("payment_id") or payload.get("id")
        raw_status = str(payload.get("payment_status") or payload.get("invoice_status") or "").lower()
        if payment_id is not None:
            payment_id = str(payment_id)

        # Docs: finished = paid; partially_paid / waiting etc. are not completion.
        is_success = raw_status == "finished"

        return {
            "provider_payment_id": payment_id or "",
            "provider_status": raw_status,
            "is_success": is_success,
        }

    def fetch_payment_status(self, *, provider_payment_id: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("NOWPAYMENTS_API_KEY_SECRET is not configured")
        pid = str(provider_payment_id or "").strip()
        if not pid:
            raise RuntimeError("provider_payment_id is required")
        headers = {"x-api-key": self.api_key}
        url = f"{self.base_url}/payment/{pid}"
        try:
            resp = httpx.get(url, headers=headers, timeout=30.0)
        except httpx.RequestError as exc:
            logger.exception("nowpayments_fetch_payment_http_error")
            raise RuntimeError("NOWPayments fetch payment failed") from exc
        if resp.status_code >= 400:
            logger.error("nowpayments_fetch_payment_bad_status {} body {}", resp.status_code, resp.text[:2000])
            raise RuntimeError(f"NOWPayments fetch payment error: HTTP {resp.status_code}")
        data = resp.json()
        if isinstance(data, dict):
            return data
        raise RuntimeError("NOWPayments fetch payment returned invalid payload")
