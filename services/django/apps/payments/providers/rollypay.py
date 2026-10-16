from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
from django.conf import settings
from loguru import logger

from .base import BasePaymentProvider


class RollyPayProvider(BasePaymentProvider):
    """
    RollyPay (https://rollypay.io): POST /api/v1/payments, webhooks with X-Signature (HMAC-SHA256).
    Docs: signing_secret + HMAC-SHA256(timestamp + "." + raw_body).
    """

    name = "rollypay"

    def __init__(self) -> None:
        self.api_key = (getattr(settings, "ROLLYPAY_API_KEY", "") or "").strip()
        self.signing_secret = (getattr(settings, "ROLLYPAY_SIGNING_SECRET", "") or "").strip()
        self.terminal_id = (getattr(settings, "ROLLYPAY_TERMINAL_ID", "") or "").strip()
        self.base_url = (
            getattr(settings, "ROLLYPAY_BASE_URL", None) or "https://rollypay.io"
        ).rstrip("/")
        self._min_amount = Decimal(str(getattr(settings, "ROLLYPAY_MIN_AMOUNT_RUB", "10.0")))
        self._currencies = ["rub"]

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
            raise RuntimeError("ROLLYPAY_API_KEY is not configured")

        fiat = (currency or "RUB").strip().upper()
        if fiat != "RUB":
            raise RuntimeError("RollyPay only supports RUB for payment_currency")

        site = str(getattr(settings, "PUBLIC_SITE_URL", "http://127.0.0.1:8000")).rstrip("/")
        rel_ok = getattr(settings, "ROLLYPAY_DEFAULT_SUCCESS_REL_PATH", "/") or "/"
        rel_fail = getattr(settings, "ROLLYPAY_DEFAULT_FAIL_REL_PATH", "/") or "/"
        if not str(rel_ok).startswith("/"):
            rel_ok = "/" + str(rel_ok).lstrip("/")
        if not str(rel_fail).startswith("/"):
            rel_fail = "/" + str(rel_fail).lstrip("/")
        default_success = f"{site}{rel_ok}"
        default_fail = f"{site}{rel_fail}"
        success_url = success_url or default_success
        cancel_url = cancel_url or default_fail

        amount_str = str(Decimal(amount).quantize(Decimal("0.01")))
        description = (order_description.strip() or f"Payment {reference_id}")[:512]
        body: dict[str, Any] = {
            "amount": amount_str,
            "payment_currency": "RUB",
            "order_id": str(reference_id),
            "description": description,
            "success_redirect_url": success_url,
            "fail_redirect_url": cancel_url,
        }
        if self.terminal_id:
            body["terminal_id"] = self.terminal_id

        url = f"{self.base_url}/api/v1/payments"
        nonce = str(uuid.uuid4())
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "X-Nonce": nonce,
        }
        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=45.0)
        except httpx.RequestError as exc:
            logger.exception("rollypay_create_payment_http_error")
            raise RuntimeError("RollyPay request failed") from exc

        if resp.status_code >= 400:
            logger.error(
                "rollypay_create_payment_bad_status {} body {}",
                resp.status_code,
                resp.text[:2000],
            )
            raise RuntimeError(f"RollyPay payment error: HTTP {resp.status_code}")

        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("RollyPay returned invalid payload")

        pay_url = data.get("pay_url") or ""
        ext_id = data.get("payment_id")
        if ext_id is not None:
            ext_id = str(ext_id)
        return {
            "invoice_url": pay_url,
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
        if not self.signing_secret:
            logger.warning("ROLLYPAY_SIGNING_SECRET missing; webhook rejected")
            return False, None
        if not signature_header or not webhook_timestamp:
            return False, None
        try:
            raw_text = raw_body.decode("utf-8")
            payload = json.loads(raw_text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False, None
        if not isinstance(payload, dict):
            return False, None

        ts = str(webhook_timestamp).strip()
        sig = str(signature_header).strip().lower()
        mac = hmac.new(
            self.signing_secret.encode("utf-8"),
            (ts + "." + raw_text).encode("utf-8"),
            hashlib.sha256,
        )
        expected = mac.hexdigest().lower()
        try:
            ok = hmac.compare_digest(expected, sig)
        except Exception:
            return False, None
        if not ok:
            logger.warning(
                "rollypay_webhook_signature_mismatch header_len={}",
                len(sig),
            )
        return ok, payload

    def parse_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        payment_id = payload.get("payment_id")
        if payment_id is not None:
            payment_id = str(payment_id)
        raw_status = str(payload.get("status") or "").lower()
        event_type = str(payload.get("event_type") or "").lower()
        is_success = event_type == "payment.paid" or raw_status == "paid"

        return {
            "provider_payment_id": payment_id or "",
            "provider_status": raw_status,
            "is_success": is_success,
        }

    def fetch_payment_status(self, *, provider_payment_id: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("ROLLYPAY_API_KEY is not configured")
        pid = str(provider_payment_id or "").strip()
        if not pid:
            raise RuntimeError("provider_payment_id is required")
        url = f"{self.base_url}/api/v1/payments/{pid}"
        nonce = str(uuid.uuid4())
        headers = {"X-API-Key": self.api_key, "X-Nonce": nonce}
        try:
            resp = httpx.get(url, headers=headers, timeout=30.0)
        except httpx.RequestError as exc:
            logger.exception("rollypay_fetch_payment_http_error")
            raise RuntimeError("RollyPay fetch payment failed") from exc
        if resp.status_code >= 400:
            logger.error(
                "rollypay_fetch_payment_bad_status {} body {}",
                resp.status_code,
                resp.text[:2000],
            )
            raise RuntimeError(f"RollyPay fetch payment error: HTTP {resp.status_code}")
        data = resp.json()
        if isinstance(data, dict):
            return data
        raise RuntimeError("RollyPay fetch payment returned invalid payload")
