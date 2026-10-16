import json
import secrets
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.urls import reverse

from .services import complete_oauth_login

User = get_user_model()


def _google_redirect_uri() -> str:
    base = str(getattr(settings, "PUBLIC_SITE_URL", "http://127.0.0.1:8000") or "").strip()
    base = base.rstrip("/")
    return f"{base}{reverse('accounts:oauth-google-callback')}"


def build_google_authorize_url(request: HttpRequest) -> str:
    redirect_uri = _google_redirect_uri()
    state = secrets.token_urlsafe(24)
    request.session["google_oauth_state"] = state

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def _http_post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _http_get_json(url: str, access_token: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {access_token}")
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def handle_google_callback(request: HttpRequest) -> dict:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        return {"ok": False, "error": "Google OAuth is not configured."}

    state = request.GET.get("state", "")
    expected_state = request.session.get("google_oauth_state", "")
    if not state or not expected_state or state != expected_state:
        return {"ok": False, "error": "Invalid OAuth state."}

    code = request.GET.get("code", "")
    if not code:
        return {"ok": False, "error": "Missing OAuth code."}

    redirect_uri = _google_redirect_uri()

    token = _http_post_form(
        "https://oauth2.googleapis.com/token",
        {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )

    access_token = token.get("access_token") or ""
    if not access_token:
        return {"ok": False, "error": "Google token exchange failed."}

    info = _http_get_json("https://openidconnect.googleapis.com/v1/userinfo", access_token=access_token)
    email = (info.get("email") or "").strip().lower()
    sub = str(info.get("sub") or "").strip()

    if not email or not sub:
        return {"ok": False, "error": "Google profile is missing required fields."}

    existing_user = User.objects.filter(email__iexact=email).first()
    is_new_user = existing_user is None
    user = existing_user or User.objects.create_user(
        username=email[:150], email=email, password=None, is_active=True
    )

    given_name = (info.get("given_name") or "").strip()
    family_name = (info.get("family_name") or "").strip()
    update_fields = []
    if given_name and not (user.first_name or "").strip():
        user.first_name = given_name
        update_fields.append("first_name")
    if family_name and not (user.last_name or "").strip():
        user.last_name = family_name
        update_fields.append("last_name")
    if update_fields:
        user.save(update_fields=update_fields)

    result = complete_oauth_login(
        request,
        user=user,
        provider="google",
        provider_uid=sub,
        email_hint=email,
        meta={
            "email_verified": bool(info.get("email_verified")),
            "name": info.get("name", ""),
            "given_name": given_name,
            "family_name": family_name,
        },
        set_registration_ip=is_new_user,
    )
    return {"ok": True, "step_up_required": bool(result.get("step_up_required")), "email": email}

