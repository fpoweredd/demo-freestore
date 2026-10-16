from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.cache import cache
from loguru import logger

from apps.core.bot_api_client import post_signup_notify

from .models import AccountProfile

User = get_user_model()


def _ensure_profile(user: User) -> AccountProfile:
    profile, _ = AccountProfile.objects.get_or_create(user=user)
    return profile


def _sanitize_utm_params(raw: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(raw, dict):
        return result
    for key, value in raw.items():
        k = str(key or "").strip()
        v = str(value or "").strip()
        if k and v:
            result[k] = v
    return result


def _value_or_dash(value: str | None) -> str:
    return (value or "").strip() or "-"


def _build_signup_notify_payload(
    *,
    user: User,
    registration_method: str,
) -> dict[str, Any]:
    profile = _ensure_profile(user)
    profile.refresh_from_db()

    tg_id = getattr(profile, "tg_id", None)
    tg_username = str(getattr(profile, "tg_username", "") or "").strip()
    telegram_handle = str(getattr(profile, "telegram_handle", "") or "").strip()
    tg_auth = None
    if tg_id and tg_username:
        normalized = tg_username.lstrip("@")
        tg_auth = f"@{normalized} ({tg_id})"
    tg_handler = None
    if not tg_auth and telegram_handle:
        tg_handler = f"@{telegram_handle.lstrip('@')}"

    email = str(getattr(user, "email", "") or "").strip() or "-"
    reg_ip = str(getattr(profile, "registration_ip", "") or "").strip() or "-"

    return {
        "user_public_id": str(profile.public_id),
        "user_email": email,
        "registration_method": registration_method,
        "reg_geo": str(getattr(profile, "ip_geo", "") or "").strip(),
        "locale": str(getattr(profile, "locale", "") or "").strip(),
        "registration_ip": reg_ip,
        "utm_params": _sanitize_utm_params(getattr(profile, "utm_params", {}) or {}),
        "tg_auth": tg_auth,
        "tg_handler": tg_handler,
    }


def notify_telegram_bot_new_signup(
    *,
    user: User,
    registration_method: str,
) -> None:
    method = (registration_method or "").strip().lower()
    if method not in {"email", "google", "telegram"}:
        logger.warning("signup_notify_skipped invalid_method={}", registration_method)
        return

    profile = AccountProfile.objects.filter(user=user).only("public_id").first()
    if profile is None:
        return

    dedup_key = f"tg_signup_notify:{profile.public_id}"
    if not cache.add(dedup_key, 1, timeout=30 * 24 * 3600):
        return

    payload = _build_signup_notify_payload(
        user=user,
        registration_method=method,
    )
    if not post_signup_notify(payload):
        cache.delete(dedup_key)
        logger.warning(
            "signup_telegram_notify_failed user_public_id={} method={}",
            profile.public_id,
            method,
        )
