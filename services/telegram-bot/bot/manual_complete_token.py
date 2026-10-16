"""HMAC tokens for Telegram inline callback_data (manual order complete)."""

from __future__ import annotations

import hashlib
import hmac


def sign_manual_complete_public_id(*, order_public_id: int, secret: str) -> str:
    key = (secret or "").strip().encode("utf-8")
    if not key:
        raise ValueError("signing_secret_empty")
    return hmac.new(
        key,
        str(int(order_public_id)).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()[:12]


def manual_complete_callback_data(*, order_public_id: int, secret: str) -> str:
    """
    Keeps telegram callback_data <= 64 bytes:
    mf:<decimal id>:<12 hex chars>
    """
    sig = sign_manual_complete_public_id(order_public_id=order_public_id, secret=secret)
    raw = f"mf:{int(order_public_id)}:{sig}"
    if len(raw.encode("utf-8")) > 64:
        raise ValueError("callback_data_exceeds_telegram_limit")
    return raw


def verify_manual_complete_callback_parts(
    *, order_public_id: int, sig: str, secret: str
) -> bool:
    try:
        expected = sign_manual_complete_public_id(
            order_public_id=order_public_id, secret=secret
        )
    except ValueError:
        return False
    return hmac.compare_digest(expected, (sig or "").strip().lower())


def parse_manual_complete_callback(data: str) -> tuple[int, str] | None:
    if not data or not data.startswith("mf:"):
        return None
    parts = data.split(":")
    if len(parts) != 3:
        return None
    _prefix, id_raw, sig = parts
    try:
        oid = int(id_raw)
    except Exception:
        return None
    if oid <= 0 or len(sig) != 12:
        return None
    return (oid, sig.lower())
