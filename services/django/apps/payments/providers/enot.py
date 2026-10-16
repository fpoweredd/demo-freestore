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

# Enot signs like PHP: ksort (top-level only) + json_encode — compact, no ASCII escapes.
_ENOT_WEBHOOK_JSON_SEPARATORS = (",", ":")


def _enot_ksort_top_level(payload: dict[str, Any]) -> dict[str, Any]:
    """PHP ksort() on webhook body — nested key order preserved."""
    return {key: payload[key] for key in sorted(payload.keys())}


def _enot_webhook_canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        _enot_ksort_top_level(payload),
        separators=_ENOT_WEBHOOK_JSON_SEPARATORS,
        ensure_ascii=False,
    )


def _enot_hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        msg=message,
        digestmod=hashlib.sha256,
    ).hexdigest()


def _enot_signature_candidates(
    *, raw_body: bytes, payload: dict[str, Any]
) -> list[bytes]:
    """Bytes Enot may have signed (API version drift)."""
    candidates: list[bytes] = [raw_body]
    canonical = _enot_webhook_canonical_json(payload)
    candidates.append(canonical.encode("utf-8"))
    candidates.append(
        json.dumps(
            payload,
            sort_keys=True,
            separators=_ENOT_WEBHOOK_JSON_SEPARATORS,
            ensure_ascii=False,
        ).encode("utf-8")
    )
    return candidates


class EnotProvider(BasePaymentProvider):
    """
    Enot.io: POST /invoice/create, GET /invoice/info, webhooks with x-api-sha256-signature.
    API auth: x-api-key = shop secret key. Webhook HMAC: additional shop key.
    """

    name = "enot"

    def __init__(self) -> None:
        self.shop_id = (getattr(settings, "ENOT_SHOP_ID", "") or "").strip()
        self.api_key = (getattr(settings, "ENOT_API_KEY", "") or "").strip()
        self.webhook_secret = (
            getattr(settings, "ENOT_WEBHOOK_SECRET", "") or ""
        ).strip()
        self.base_url = (
            getattr(settings, "ENOT_BASE_URL", None) or "https://api.enot.io"
        ).rstrip("/")
        self._min_amount = Decimal(
            str(getattr(settings, "ENOT_MIN_AMOUNT_RUB", "10.0"))
        )
        self._invoice_expire_minutes = max(
            1, int(getattr(settings, "ENOT_INVOICE_EXPIRE_MINUTES", 300))
        )
        self._currencies = ["rub"]

    @property
    def min_amount(self) -> Decimal:
        return self._min_amount

    @property
    def supported_currencies(self) -> list[str]:
        return self._currencies

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
        }

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
        if not self.api_key or not self.shop_id:
            raise RuntimeError("ENOT_SHOP_ID and ENOT_API_KEY must be configured")

        fiat = (currency or "RUB").strip().upper()
        if fiat != "RUB":
            raise RuntimeError("Enot only supports RUB for this integration")

        site = str(
            getattr(settings, "PUBLIC_SITE_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        hook_url = f"{site}/webhooks/enot"
        rel_ok = getattr(settings, "ENOT_DEFAULT_SUCCESS_REL_PATH", "/") or "/"
        rel_fail = getattr(settings, "ENOT_DEFAULT_FAIL_REL_PATH", "/") or "/"
        if not str(rel_ok).startswith("/"):
            rel_ok = "/" + str(rel_ok).lstrip("/")
        if not str(rel_fail).startswith("/"):
            rel_fail = "/" + str(rel_fail).lstrip("/")
        success_url = success_url or f"{site}{rel_ok}"
        cancel_url = cancel_url or f"{site}{rel_fail}"

        amount_value = Decimal(amount).quantize(Decimal("0.01"))
        comment = (order_description.strip() or f"Payment {reference_id}")[:255]
        body: dict[str, Any] = {
            "amount": float(amount_value),
            "order_id": str(reference_id),
            "currency": fiat,
            "shop_id": self.shop_id,
            "hook_url": hook_url,
            "success_url": success_url,
            "fail_url": cancel_url,
            "comment": comment,
            "expire": self._invoice_expire_minutes,
        }

        url = f"{self.base_url}/invoice/create"
        try:
            resp = httpx.post(url, json=body, headers=self._headers(), timeout=45.0)
        except httpx.RequestError as exc:
            logger.exception("enot_create_invoice_http_error")
            raise RuntimeError("Enot request failed") from exc

        if resp.status_code >= 400:
            logger.error(
                "enot_create_invoice_bad_status {} body {}",
                resp.status_code,
                resp.text[:2000],
            )
            raise RuntimeError(f"Enot invoice error: HTTP {resp.status_code}")

        envelope = resp.json()
        if not isinstance(envelope, dict):
            raise RuntimeError("Enot returned invalid payload")
        data = envelope.get("data")
        if not isinstance(data, dict):
            err = envelope.get("error") or "unknown"
            raise RuntimeError(f"Enot invoice error: {err}")

        invoice_url = data.get("url") or ""
        ext_id = data.get("id")
        if ext_id is not None:
            ext_id = str(ext_id)
        return {
            "invoice_url": invoice_url,
            "provider_payment_id": ext_id,
            "raw": envelope,
        }

    def verify_webhook(
        self,
        *,
        raw_body: bytes,
        signature_header: str | None,
        webhook_timestamp: str | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        if not self.webhook_secret:
            logger.warning("ENOT_WEBHOOK_SECRET missing; webhook rejected")
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

        sig = str(signature_header).strip().lower()
        if sig.startswith("sha256="):
            sig = sig.split("=", 1)[1].strip()

        secret = self.webhook_secret
        for idx, message in enumerate(
            _enot_signature_candidates(raw_body=raw_body, payload=payload)
        ):
            try:
                expected = _enot_hmac_hex(secret, message).lower()
                if hmac.compare_digest(expected, sig):
                    if idx > 0:
                        logger.info("enot_webhook_signature_matched variant={}", idx)
                    return True, payload
            except Exception:
                continue

        logger.warning(
            "enot_webhook_signature_mismatch header_len={} body_len={} keys={}",
            len(sig),
            len(raw_body),
            sorted(payload.keys()),
        )
        return False, payload

    def parse_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        if isinstance(data, dict):
            merged = {**data, **{k: v for k, v in payload.items() if k != "data"}}
            payload = merged

        invoice_id = payload.get("invoice_id") or payload.get("id")
        if invoice_id is not None:
            invoice_id = str(invoice_id)
        raw_status = str(payload.get("status") or "").lower()
        is_success = raw_status == "success"

        return {
            "provider_payment_id": invoice_id or "",
            "provider_status": raw_status,
            "is_success": is_success,
        }

    def fetch_payment_status(self, *, provider_payment_id: str) -> dict[str, Any]:
        if not self.api_key or not self.shop_id:
            raise RuntimeError("ENOT_SHOP_ID and ENOT_API_KEY must be configured")
        pid = str(provider_payment_id or "").strip()
        if not pid:
            raise RuntimeError("provider_payment_id is required")

        url = f"{self.base_url}/invoice/info"
        params = {"invoice_id": pid, "shop_id": self.shop_id}
        try:
            resp = httpx.get(url, params=params, headers=self._headers(), timeout=30.0)
        except httpx.RequestError as exc:
            logger.exception("enot_fetch_invoice_http_error")
            raise RuntimeError("Enot fetch invoice failed") from exc
        if resp.status_code >= 400:
            logger.error(
                "enot_fetch_invoice_bad_status {} body {}",
                resp.status_code,
                resp.text[:2000],
            )
            raise RuntimeError(f"Enot fetch invoice error: HTTP {resp.status_code}")

        envelope = resp.json()
        if not isinstance(envelope, dict):
            raise RuntimeError("Enot fetch invoice returned invalid payload")
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Enot fetch invoice missing data")

        flat = dict(data)
        flat["invoice_id"] = flat.get("invoice_id") or pid
        flat["payment_id"] = flat["invoice_id"]
        flat["order_id"] = flat.get("order_id") or ""
        flat["status"] = flat.get("status") or ""
        return flat
