import json
import urllib.parse
import urllib.request

from django.conf import settings


def verify_turnstile(response_token: str, remote_ip: str = "") -> tuple[bool, str]:
    """
    Verifies Cloudflare Turnstile token server-side.
    Returns (ok, error_code).
    """
    secret = getattr(settings, "TURNSTILE_SECRET_KEY", "") or ""
    if not secret:
        return False, "turnstile_not_configured"
    token = (response_token or "").strip()
    if not token:
        return False, "missing_turnstile_token"

    data = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip

    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data=body,
        method="POST",
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:  # nosec B310
            raw = resp.read().decode("utf-8")
        payload = json.loads(raw)
    except Exception:
        return False, "turnstile_verify_failed"

    ok = bool(payload.get("success"))
    if ok:
        return True, ""
    codes = payload.get("error-codes") or []
    code = codes[0] if isinstance(codes, list) and codes else "turnstile_invalid"
    return False, str(code)

