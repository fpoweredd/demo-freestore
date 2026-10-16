import ipaddress
from datetime import timedelta

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.db import transaction
from django.utils import timezone

from .models import AccountIdentity, AccountProfile, PasswordResetRequest
from .telegram_notify import notify_telegram_bot_new_signup
from .tracking import apply_first_touch_tracking

User = get_user_model()


def client_ip_from_request(request) -> str | None:
    if request is None:
        return None
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def maybe_set_registration_ip(profile: AccountProfile, ip: str | None) -> None:
    if profile.registration_ip:
        return
    if not ip:
        return
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return
    profile.registration_ip = ip
    profile.save(update_fields=["registration_ip", "updated_at"])

def _unique_username_from_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not email:
        return "user"
    base = email[:150]
    if not User.objects.filter(username=base).exists():
        return base
    if "@" not in email:
        idx = 1
        while True:
            candidate = f"{base[:140]}+{idx}"
            if not User.objects.filter(username=candidate).exists():
                return candidate[:150]
            idx += 1
    local, domain = email.split("@", 1)
    idx = 1
    while True:
        candidate = f"{local}+{idx}@{domain}"
        candidate = candidate[:150]
        if not User.objects.filter(username=candidate).exists():
            return candidate
        idx += 1


def ensure_profile(user):
    profile, _ = AccountProfile.objects.get_or_create(user=user)
    return profile


@transaction.atomic
def register_user(
    email: str,
    password: str,
    telegram_handle: str = "",
    *,
    registration_ip: str | None = None,
    request=None,
):
    email = (email or "").strip().lower()
    user = User.objects.filter(email__iexact=email).first()
    created = False
    if not user:
        username = _unique_username_from_email(email)
        user = User.objects.create_user(username=username, email=email, password=password, is_active=True)
        created = True
    else:
        if not user.has_usable_password():
            user.set_password(password)
            user.save(update_fields=["password"])
    profile = ensure_profile(user)
    if created:
        maybe_set_registration_ip(profile, registration_ip)
        if telegram_handle:
            profile.telegram_handle = telegram_handle
            profile.save(update_fields=["telegram_handle", "updated_at"])
        if request is not None:
            apply_first_touch_tracking(profile, request)
        notify_telegram_bot_new_signup(user=user, registration_method="email")
    elif telegram_handle:
        profile.telegram_handle = telegram_handle
        profile.save(update_fields=["telegram_handle", "updated_at"])
    return user, created


def login_with_email_password(request, email: str, password: str):
    email = (email or "").strip().lower()
    user = User.objects.filter(email__iexact=email).first()
    if not user:
        return None
    auth_user = authenticate(request, username=user.username, password=password)
    if not auth_user:
        return None
    login(request, auth_user)
    return auth_user


def logout_current_user(request):
    logout(request)


def issue_password_reset(email: str):
    email = (email or "").strip().lower()
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if not user:
        return None
    reset = PasswordResetRequest.objects.create(
        user=user,
        email_snapshot=user.email,
        expires_at=timezone.now() + timedelta(hours=12),
    )
    return reset


@transaction.atomic
def consume_password_reset(token: str, new_password: str):
    reset = PasswordResetRequest.objects.filter(token=token).select_related("user").first()
    if not reset or not reset.is_valid:
        return None
    user = reset.user
    user.set_password(new_password)
    user.save(update_fields=["password"])
    reset.consumed_at = timezone.now()
    reset.save(update_fields=["consumed_at", "updated_at"])
    return user


def link_oauth_identity(user, provider: str, provider_uid: str, email_hint: str = "", meta: dict | None = None):
    identity, _ = AccountIdentity.objects.update_or_create(
        provider=provider,
        provider_uid=provider_uid,
        defaults={
            "user": user,
            "email_hint": email_hint,
            "meta": meta or {},
        },
    )
    return identity


def complete_oauth_login(
    request,
    user,
    provider: str,
    provider_uid: str,
    email_hint: str = "",
    meta: dict | None = None,
    *,
    set_registration_ip: bool = False,
):
    profile = ensure_profile(user)
    link_oauth_identity(user=user, provider=provider, provider_uid=provider_uid, email_hint=email_hint, meta=meta)

    if set_registration_ip:
        maybe_set_registration_ip(profile, client_ip_from_request(request))
        apply_first_touch_tracking(profile, request)
        notify_telegram_bot_new_signup(user=user, registration_method=provider)

    needs_step_up = provider == "google" and user.has_usable_password() and profile.require_password_after_oauth
    if needs_step_up:
        request.session["oauth_step_up_user_id"] = user.id
        request.session["oauth_step_up_provider"] = provider
        return {"step_up_required": True}

    login(request, user)
    return {"step_up_required": False}


def verify_oauth_step_up(request, password: str):
    user_id = request.session.get("oauth_step_up_user_id")
    if not user_id:
        return None
    user = User.objects.filter(id=user_id, is_active=True).first()
    if not user:
        return None
    auth_user = authenticate(request, username=user.username, password=password)
    if not auth_user:
        return None
    login(request, auth_user)
    request.session.pop("oauth_step_up_user_id", None)
    request.session.pop("oauth_step_up_provider", None)
    return auth_user
