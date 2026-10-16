import base64
import hashlib
import hmac
import json
import time
import urllib.parse

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.conf import settings
from django.contrib.auth import get_user_model

from .models import AccountIdentity
from .services import complete_oauth_login, ensure_profile, link_oauth_identity

User = get_user_model()
TELEGRAM_WEBAPP_PROD_PUBLIC_KEY_HEX = (
    "e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d"
)
TELEGRAM_WEBAPP_TEST_PUBLIC_KEY_HEX = (
    "40055058a4ee38156a06562e52eece92a771bcd8346a8c4615cb7376eddf72ec"
)


def _build_data_check_string(
    data: dict, include_signature_prefix: bool, bot_id: str
) -> str:
    keys = sorted(k for k in data.keys() if k not in {"hash", "signature"})
    lines = [f"{k}={data[k]}" for k in keys]
    payload = "\n".join(lines)
    if include_signature_prefix:
        return f"{bot_id}:WebAppData\n{payload}"
    return payload


def _decode_base64url(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def verify_telegram_webapp_init_data_detailed(
    init_data: str,
) -> tuple[dict | None, str, dict]:
    debug_info = {
        "init_data_len": len(init_data or ""),
    }
    token = settings.TELEGRAM_BOT_TOKEN or ""
    if not token or not init_data:
        return None, "missing_token_or_init_data", debug_info

    # Telegram sends initData as a query string, so parse it exactly as pairs.
    pairs = urllib.parse.parse_qsl(
        init_data,
        keep_blank_values=True,
        strict_parsing=False,
        encoding="utf-8",
        errors="strict",
    )
    data = {k: v for k, v in pairs}
    given_hash = (data.get("hash") or "").strip()
    debug_info["has_signature"] = bool((data.get("signature") or "").strip())
    debug_info["hash_len"] = len(given_hash)
    if not given_hash:
        return None, "missing_hash", debug_info

    auth_date_raw = (data.get("auth_date") or "0").strip()
    if not auth_date_raw.isdigit():
        return None, "invalid_auth_date", debug_info
    auth_date = int(auth_date_raw)
    now_ts = int(time.time())
    debug_info["auth_date_age_sec"] = abs(now_ts - auth_date)
    if abs(now_ts - auth_date) > 900:
        return None, "auth_date_expired", debug_info

    bot_id = token.split(":", 1)[0].strip()
    data_check_string = _build_data_check_string(
        data, include_signature_prefix=False, bot_id=bot_id
    )

    # Telegram docs use shorthand notation for HMAC arguments.
    # Some implementations interpret parameter order differently, so we
    # compute both variants and accept either matching signature.
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    secret_key_alt = hmac.new(
        token.encode("utf-8"), b"WebAppData", hashlib.sha256
    ).digest()
    expected_hash_alt = hmac.new(
        secret_key_alt, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    hash_ok = hmac.compare_digest(
        expected_hash.lower(), given_hash.lower()
    ) or hmac.compare_digest(expected_hash_alt.lower(), given_hash.lower())
    signature_ok = False
    signature_raw = (data.get("signature") or "").strip()
    if signature_raw and bot_id:
        signature_payload = _build_data_check_string(
            data, include_signature_prefix=True, bot_id=bot_id
        )
        try:
            signature_bytes = _decode_base64url(signature_raw)
            for pub_hex in (
                TELEGRAM_WEBAPP_PROD_PUBLIC_KEY_HEX,
                TELEGRAM_WEBAPP_TEST_PUBLIC_KEY_HEX,
            ):
                try:
                    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
                    pub.verify(signature_bytes, signature_payload.encode("utf-8"))
                    signature_ok = True
                    break
                except Exception:
                    continue
        except Exception:
            signature_ok = False

    debug_info["signature_ok"] = signature_ok
    if not hash_ok and not signature_ok:
        token_fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
        debug_info.update(
            {
                "expected_hash_prefix": expected_hash[:12],
                "expected_hash_alt_prefix": expected_hash_alt[:12],
                "given_hash_prefix": given_hash[:12],
                "bot_id_prefix": token.split(":", 1)[0][:8],
                "token_fp": token_fingerprint,
            }
        )
        return None, "bad_hash", debug_info

    user_raw = data.get("user") or ""
    if not user_raw:
        return None, "missing_user", debug_info
    try:
        user_obj = json.loads(user_raw)
    except Exception:
        return None, "invalid_user_json", debug_info

    if not isinstance(user_obj, dict):
        return None, "invalid_user_payload", debug_info
    verified = {
        "id": str(user_obj.get("id") or ""),
        "username": str(user_obj.get("username") or ""),
        "first_name": str(user_obj.get("first_name") or ""),
        "last_name": str(user_obj.get("last_name") or ""),
        "auth_source": "miniapp_tg",
    }
    if not verified["id"]:
        return None, "missing_user_id", debug_info
    return verified, "ok", debug_info


def verify_telegram_webapp_init_data(init_data: str) -> dict | None:
    verified, _, _ = verify_telegram_webapp_init_data_detailed(init_data)
    return verified


def upsert_user_from_telegram(request, verified: dict) -> dict:
    tg_id = str(verified.get("id") or "").strip()
    if not tg_id:
        return {"ok": False}

    existing_identity = (
        AccountIdentity.objects.filter(provider="telegram", provider_uid=tg_id)
        .select_related("user")
        .first()
    )
    created_new_user = False
    if existing_identity:
        user = existing_identity.user
    else:
        username = f"tg_{tg_id}"[:150]
        user = User.objects.filter(username=username).first()
        if not user:
            user = User.objects.create_user(
                username=username, email="", password=None, is_active=True
            )
            created_new_user = True
        identity_meta = dict(verified)
        link_oauth_identity(
            user=user,
            provider="telegram",
            provider_uid=tg_id,
            email_hint="",
            meta=identity_meta,
        )

    profile = ensure_profile(user)
    profile.tg_id = int(tg_id)
    profile.tg_username = verified.get("username", "") or ""
    profile.save(update_fields=["tg_id", "tg_username", "updated_at"])

    first_name = (verified.get("first_name") or "").strip()
    last_name = (verified.get("last_name") or "").strip()
    update_fields = []
    if first_name and not (user.first_name or "").strip():
        user.first_name = first_name
        update_fields.append("first_name")
    if last_name and not (user.last_name or "").strip():
        user.last_name = last_name
        update_fields.append("last_name")
    if update_fields:
        user.save(update_fields=update_fields)

    identity_meta = dict(verified)
    result = complete_oauth_login(
        request,
        user=user,
        provider="telegram",
        provider_uid=tg_id,
        email_hint="",
        meta=identity_meta,
        set_registration_ip=created_new_user,
    )
    return {"ok": True, "step_up_required": bool(result.get("step_up_required"))}
