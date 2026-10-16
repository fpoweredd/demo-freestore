from __future__ import annotations

from typing import Any

import httpx
from django.conf import settings
from loguru import logger


def post_order_notify(payload: dict[str, Any]) -> bool:
    url = str(getattr(settings, "BOT_INTERNAL_ORDER_API_URL", "") or "").strip()
    api_key = str(getattr(settings, "BOT_INTERNAL_API_KEY", "") or "").strip()
    if not url or not api_key:
        return False

    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"x-api-key": api_key},
            timeout=8.0,
        )
        if response.status_code >= 300:
            logger.warning(
                "telegram_bot_order_notify_failed status={} body={}",
                response.status_code,
                response.text[:500],
            )
            return False
        return True
    except Exception:
        logger.exception("telegram_bot_order_notify_exception")
        return False


def post_manual_order_notify(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Posts a manual-fulfillment order notification to the telegram-bot internal API.
    Returns response JSON on success, otherwise None.
    """
    url = str(getattr(settings, "BOT_INTERNAL_MANUAL_ORDER_API_URL", "") or "").strip()
    api_key = str(getattr(settings, "BOT_INTERNAL_API_KEY", "") or "").strip()
    if not url or not api_key:
        return None

    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"x-api-key": api_key},
            timeout=8.0,
        )
        if response.status_code >= 300:
            logger.warning(
                "telegram_bot_manual_order_notify_failed status={} body={}",
                response.status_code,
                response.text[:500],
            )
            return None
        try:
            return response.json()
        except Exception:
            return {"ok": True}
    except Exception:
        logger.exception("telegram_bot_manual_order_notify_exception")
        return None

def post_preorder_paid_notify(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Posts preorder-paid notification. Returns parsed JSON on HTTP success, else None.
    On success, body includes ok=True and, when a message was posted, chat_id, message_id, text.
    """
    url = str(getattr(settings, "BOT_INTERNAL_PREORDER_API_URL", "") or "").strip()
    api_key = str(getattr(settings, "BOT_INTERNAL_API_KEY", "") or "").strip()
    if not url or not api_key:
        return None

    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"x-api-key": api_key},
            timeout=8.0,
        )
        if response.status_code >= 300:
            logger.warning(
                "telegram_bot_preorder_notify_failed status={} body={}",
                response.status_code,
                response.text[:500],
            )
            return None
        try:
            return response.json()
        except Exception:
            return {"ok": True}
    except Exception:
        logger.exception("telegram_bot_preorder_notify_exception")
        return None


def post_preorder_fulfilled_notify(payload: dict[str, Any]) -> bool:
    url = str(
        getattr(settings, "BOT_INTERNAL_PREORDER_FULFILLED_API_URL", "") or ""
    ).strip()
    api_key = str(getattr(settings, "BOT_INTERNAL_API_KEY", "") or "").strip()
    if not url or not api_key:
        return False

    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"x-api-key": api_key},
            timeout=8.0,
        )
        if response.status_code >= 300:
            logger.warning(
                "telegram_bot_preorder_fulfilled_notify_failed status={} body={}",
                response.status_code,
                response.text[:500],
            )
            return False
        return True
    except Exception:
        logger.exception("telegram_bot_preorder_fulfilled_notify_exception")
        return False


def post_topup_notify(payload: dict[str, Any]) -> bool:
    url = str(getattr(settings, "BOT_INTERNAL_TOPUP_API_URL", "") or "").strip()
    api_key = str(getattr(settings, "BOT_INTERNAL_API_KEY", "") or "").strip()
    if not url or not api_key:
        return False

    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"x-api-key": api_key},
            timeout=8.0,
        )
        if response.status_code >= 300:
            logger.warning(
                "telegram_bot_topup_notify_failed status={} body={}",
                response.status_code,
                response.text[:500],
            )
            return False
        return True
    except Exception:
        logger.exception("telegram_bot_topup_notify_exception")
        return False


def post_signup_notify(payload: dict[str, Any]) -> bool:
    url = str(getattr(settings, "BOT_INTERNAL_SIGNUP_API_URL", "") or "").strip()
    api_key = str(getattr(settings, "BOT_INTERNAL_API_KEY", "") or "").strip()
    if not url or not api_key:
        return False

    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"x-api-key": api_key},
            timeout=8.0,
        )
        if response.status_code >= 300:
            logger.warning(
                "telegram_bot_signup_notify_failed status={} body={}",
                response.status_code,
                response.text[:500],
            )
            return False
        return True
    except Exception:
        logger.exception("telegram_bot_signup_notify_exception")
        return False


def post_payment_error_notify(payload: dict[str, Any]) -> bool:
    url = str(getattr(settings, "BOT_INTERNAL_PAYMENTS_ERROR_API_URL", "") or "").strip()
    api_key = str(getattr(settings, "BOT_INTERNAL_API_KEY", "") or "").strip()
    if not url or not api_key:
        return False

    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"x-api-key": api_key},
            timeout=8.0,
        )
        if response.status_code >= 300:
            logger.warning(
                "telegram_bot_payment_error_notify_failed status={} body={}",
                response.status_code,
                response.text[:500],
            )
            return False
        return True
    except Exception:
        logger.exception("telegram_bot_payment_error_notify_exception")
        return False
