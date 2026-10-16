import base64
import hashlib
import json
import secrets
import urllib.parse
import urllib.request

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse
from django.db.models import Q

from .services import complete_oauth_login, ensure_profile, link_oauth_identity


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _pkce_verifier() -> str:
    return _b64url(secrets.token_bytes(32))


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return _b64url(digest)


def build_telegram_oidc_authorize_url(request: HttpRequest) -> str:
    redirect_uri = request.build_absolute_uri(reverse("accounts:telegram-oidc-callback"))
    state = secrets.token_urlsafe(24)
    verifier = _pkce_verifier()
    challenge = _pkce_challenge(verifier)

    request.session["tg_oidc_state"] = state
    request.session["tg_oidc_verifier"] = verifier

    params = {
        "client_id": settings.TELEGRAM_OIDC_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return "https://oauth.telegram.org/auth?" + urllib.parse.urlencode(params)


def _http_post_form(url: str, data: dict, basic_user: str = "", basic_pass: str = "") -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if basic_user and basic_pass:
        token = base64.b64encode(f"{basic_user}:{basic_pass}".encode("utf-8")).decode("ascii")
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _rsa_key_from_jwk(jwk: dict):
    n = int.from_bytes(base64.urlsafe_b64decode(jwk["n"] + "=="), "big")
    e = int.from_bytes(base64.urlsafe_b64decode(jwk["e"] + "=="), "big")
    pub = rsa.RSAPublicNumbers(e, n).public_key()
    return pub


def handle_telegram_oidc_callback(request: HttpRequest) -> dict:
    if not settings.TELEGRAM_OIDC_CLIENT_ID or not settings.TELEGRAM_OIDC_CLIENT_SECRET:
        return {"ok": False, "error": "Telegram OIDC is not configured."}

    state = request.GET.get("state", "")
    expected_state = request.session.get("tg_oidc_state", "")
    if not state or not expected_state or state != expected_state:
        return {"ok": False, "error": "Invalid OAuth state."}

    code = request.GET.get("code", "")
    if not code:
        return {"ok": False, "error": "Missing OAuth code."}

    verifier = request.session.get("tg_oidc_verifier", "")
    if not verifier:
        return {"ok": False, "error": "Missing PKCE verifier."}

    redirect_uri = request.build_absolute_uri(reverse("accounts:telegram-oidc-callback"))
    token = _http_post_form(
        "https://oauth.telegram.org/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": settings.TELEGRAM_OIDC_CLIENT_ID,
            "code_verifier": verifier,
        },
        basic_user=settings.TELEGRAM_OIDC_CLIENT_ID,
        basic_pass=settings.TELEGRAM_OIDC_CLIENT_SECRET,
    )

    id_token = token.get("id_token") or ""
    if not id_token:
        return {"ok": False, "error": "Missing id_token."}

    jwks = _http_get_json("https://oauth.telegram.org/.well-known/jwks.json")
    keys = jwks.get("keys") or []
    header = jwt.get_unverified_header(id_token)
    kid = header.get("kid")
    jwk = next((k for k in keys if k.get("kid") == kid), None) or (keys[0] if keys else None)
    if not jwk:
        return {"ok": False, "error": "JWKS missing."}

    public_key = _rsa_key_from_jwk(jwk)
    claims = jwt.decode(
        id_token,
        key=public_key,
        algorithms=["RS256"],
        audience=settings.TELEGRAM_OIDC_CLIENT_ID,
        options={"require": ["exp", "iat", "sub"]},
        leeway=300,
    )

    sub = str(claims.get("sub") or "").strip()
    if not sub:
        return {"ok": False, "error": "Missing sub."}

    tg_username = (
        (claims.get("preferred_username") or "").strip()
        or (claims.get("username") or "").strip()
    )
    given_name = (
        (claims.get("given_name") or "").strip()
        or (claims.get("first_name") or "").strip()
    )
    family_name = (
        (claims.get("family_name") or "").strip()
        or (claims.get("last_name") or "").strip()
    )
    if not given_name and not family_name:
        full_name = (claims.get("name") or "").strip()
        if full_name:
            parts = [p for p in full_name.split(" ") if p]
            if parts:
                given_name = parts[0]
                family_name = " ".join(parts[1:]).strip()

    # Telegram numeric user id (preferred for username/display).
    tg_numeric_id = claims.get("id")
    tg_numeric_id_str = str(tg_numeric_id).strip() if tg_numeric_id is not None else ""

    provider_uid = tg_numeric_id_str or sub

    # Create/find user by telegram identity.
    # Prefer numeric Telegram user id to keep OIDC and Mini App linked
    # to the same identity and prevent duplicate accounts.
    from django.contrib.auth import get_user_model
    from .models import AccountIdentity

    User = get_user_model()
    existing = (
        AccountIdentity.objects.filter(
            provider="telegram"
        )
        .filter(Q(provider_uid=provider_uid) | Q(provider_uid=sub))
        .select_related("user")
        .first()
    )
    set_registration_ip = False
    if existing:
        user = existing.user
    else:
        username_source = provider_uid
        username = f"tg_{username_source}"[:150]
        user = User.objects.filter(username=username).first()
        if not user:
            user = User.objects.create_user(username=username, email="", password=None, is_active=True)
            set_registration_ip = True
        identity_meta = dict(claims)
        identity_meta["auth_source"] = "telegram"
        link_oauth_identity(
            user=user,
            provider="telegram",
            provider_uid=provider_uid,
            email_hint="",
            meta=identity_meta,
        )

    # Keep username consistent with numeric Telegram ID when available.
    if tg_numeric_id_str:
        desired_username = f"tg_{tg_numeric_id_str}"[:150]
        if user.username != desired_username and not User.objects.filter(username=desired_username).exclude(id=user.id).exists():
            user.username = desired_username
            user.save(update_fields=["username"])

    profile = ensure_profile(user)
    if tg_numeric_id is not None and str(tg_numeric_id).strip():
        try:
            profile.tg_id = int(tg_numeric_id)
        except Exception:
            pass
    profile.tg_username = tg_username
    profile.save(update_fields=["tg_id", "tg_username", "updated_at"])

    update_fields = []
    if given_name and not (user.first_name or "").strip():
        user.first_name = given_name
        update_fields.append("first_name")
    if family_name and not (user.last_name or "").strip():
        user.last_name = family_name
        update_fields.append("last_name")
    if update_fields:
        user.save(update_fields=update_fields)

    identity_meta = dict(claims)
    identity_meta["auth_source"] = "telegram"
    result = complete_oauth_login(
        request,
        user=user,
        provider="telegram",
        provider_uid=provider_uid,
        email_hint="",
        meta=identity_meta,
        set_registration_ip=set_registration_ip,
    )
    return {"ok": True, "step_up_required": bool(result.get("step_up_required"))}

