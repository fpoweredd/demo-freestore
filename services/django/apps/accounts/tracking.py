from __future__ import annotations

import ipaddress
import urllib.request

from django.utils import timezone


def get_client_ip(request) -> str | None:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def get_country_code_from_request(request) -> str:
    code = (
        request.headers.get("CF-IPCountry")
        or request.headers.get("X-Country-Code")
        or request.headers.get("X-Geo-Country")
        or ""
    )
    code = (code or "").strip().upper()
    return code[:2] if len(code) >= 2 else ""


def _is_public_ip(ip: str | None) -> bool:
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_multicast
    )


def lookup_country_by_ip(ip: str | None) -> str:
    if not _is_public_ip(ip):
        return ""
    try:
        url = f"https://ipapi.co/{ip}/country/"
        with urllib.request.urlopen(url, timeout=2.0) as resp:  # nosec B310
            raw = resp.read().decode("utf-8").strip().upper()
        return raw[:2] if len(raw) >= 2 and raw.isalpha() else ""
    except Exception:
        return ""


def get_locale_from_accept_language(request) -> str:
    raw = (request.headers.get("Accept-Language") or "").strip()
    if not raw:
        return ""
    first = raw.split(",")[0].strip()
    if not first:
        return ""
    return first[:32]


def apply_first_touch_tracking(profile, request) -> None:
    """
    Capture registration geo, locale, and UTM params once (first authenticated touch).
    """
    if request is None:
        return

    update_fields: list[str] = []

    profile.last_active = timezone.now()
    profile.last_session_key = request.session.session_key or ""
    profile.last_ip = get_client_ip(request)
    profile.last_user_agent = (request.headers.get("User-Agent") or "")[:255]
    update_fields.extend(
        ["last_active", "last_session_key", "last_ip", "last_user_agent", "updated_at"]
    )

    cc = get_country_code_from_request(request)
    if not cc:
        cc = lookup_country_by_ip(profile.last_ip)
    if cc and not profile.ip_geo:
        profile.ip_geo = cc
        update_fields.append("ip_geo")

    locale = get_locale_from_accept_language(request)
    if locale and not profile.locale:
        profile.locale = locale
        update_fields.append("locale")

    utm = request.session.get("utm_params")
    if isinstance(utm, dict) and utm:
        current_profile_utm = profile.utm_params or {}
        if isinstance(current_profile_utm, dict) and not current_profile_utm:
            captured: dict[str, str] = {}
            for key, value in utm.items():
                k = str(key or "").strip()
                v = str(value or "").strip()
                if k and v:
                    captured[k] = v
            if captured:
                profile.utm_params = captured
                update_fields.append("utm_params")

    profile.save(update_fields=list(dict.fromkeys(update_fields)))


def apply_session_tracking(profile, request) -> None:
    """Updates profile on each authenticated request (middleware path)."""
    apply_first_touch_tracking(profile, request)
