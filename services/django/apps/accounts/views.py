import logging
from datetime import timedelta
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.ui_text import ui_text
from apps.notifications.mailing import (
    send_password_reset_email,
    send_registration_info_email,
)

from .forms import (
    LoginForm,
    OAuthStepUpForm,
    PasswordChangeFromProfileForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
    PasswordSetFromGoogleForm,
    ProfileUpdateForm,
    RegisterForm,
    SetEmailOnceForm,
)
from .models import AccountProfile, PasswordResetRequest
from .oauth_google import build_google_authorize_url, handle_google_callback
from .oauth_telegram import (
    upsert_user_from_telegram,
    verify_telegram_webapp_init_data_detailed,
)
from .oauth_telegram_oidc import (
    build_telegram_oidc_authorize_url,
    handle_telegram_oidc_callback,
)
from .serializers import (
    AccountMeSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
)
from .services import (
    client_ip_from_request,
    login_with_email_password,
    logout_current_user,
    register_user,
    verify_oauth_step_up,
)
from .turnstile import verify_turnstile

User = get_user_model()
logger = logging.getLogger(__name__)
PASSWORD_RESET_TOKEN_SESSION_KEY = "password_reset_token"
_BALANCE_TOPUP_RETURN_SESSION_KEY = "balance_topup_return_path"


def _safe_internal_path(request, path: str) -> bool:
    path = (path or "").strip()
    if not path.startswith("/") or path.startswith("//"):
        return False
    return url_has_allowed_host_and_scheme(
        url=path,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    )


def _balance_topup_next_from_referer(request) -> str | None:
    ref = (request.META.get("HTTP_REFERER") or "").strip()
    if not ref:
        return None
    try:
        parsed = urlparse(ref)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = parsed.netloc.split("@")[-1]
    if host != request.get_host():
        return None
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    if _safe_internal_path(request, path):
        return path
    return None


def _resolve_balance_topup_return_path(request, post_next: str) -> str:
    """Same-origin path to open after provider redirect (POST next, then Referer, else home)."""
    candidate = (post_next or "").strip()
    if candidate and _safe_internal_path(request, candidate):
        return candidate
    from_ref = _balance_topup_next_from_referer(request)
    if from_ref:
        return from_ref
    return "/"


def _redirect_to_balance_form(request, post_next: str = "") -> HttpResponse:
    n = (post_next or "").strip()
    if n and _safe_internal_path(request, n):
        q = urlencode({"next": n})
        return redirect(f"{reverse('accounts:balance')}?{q}")
    return redirect("accounts:balance")


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _auth_full_page_context(ctx: dict) -> dict:
    """Keep django messages in auth card, not in fixed #django-messages (base)."""
    out = dict(ctx)
    out["auth_messages_only_inline"] = True
    return out


def _render_auth_partial(request, template_name, context):
    site_key = getattr(settings, "TURNSTILE_SITE_KEY", "") or ""
    return render(
        request,
        template_name,
        {
            "auth_message": "",
            "auth_message_kind": "",
            "captcha_required": False,
            "turnstile_site_key": site_key,
            **context,
            "is_htmx": _is_htmx(request),
        },
    )


def _client_ip(request) -> str:
    return (client_ip_from_request(request) or "").strip()


def _login_fail_cache_key(request) -> str:
    session_key = (
        getattr(getattr(request, "session", None), "session_key", "") or ""
    ).strip()
    ip = _client_ip(request)
    return f"login_fail:{session_key}:{ip}"


def _login_fail_count(request) -> int:
    try:
        return int(cache.get(_login_fail_cache_key(request), 0) or 0)
    except Exception:
        return 0


def _bump_login_fail(request) -> int:
    key = _login_fail_cache_key(request)
    try:
        current = int(cache.get(key, 0) or 0)
    except Exception:
        current = 0
    current += 1
    cache.set(key, current, timeout=60 * 30)  # 30 minutes
    return current


def _reset_login_fail(request) -> None:
    cache.delete(_login_fail_cache_key(request))


def _turnstile_required_for_login(request) -> bool:
    threshold = int(getattr(settings, "TURNSTILE_LOGIN_FAIL_THRESHOLD", 3) or 3)
    if threshold <= 0:
        return False
    return _login_fail_count(request) >= threshold


def _verify_turnstile_or_error(request) -> tuple[bool, str]:
    token = (request.POST.get("cf-turnstile-response") or "").strip()
    ok, code = verify_turnstile(token, remote_ip=_client_ip(request))
    if ok:
        return True, ""
    return False, "Please confirm you are not a robot."


def _queue_registration_info_email(email: str) -> None:
    email = (email or "").strip().lower()
    if not email:
        return
    try:
        from apps.notifications.tasks import send_registration_info_email_task

        send_registration_info_email_task.apply_async(
            args=[email],
            queue=getattr(settings, "CELERY_EMAIL_QUEUE", "email"),
            retry=False,
        )
    except Exception:
        logger.exception("registration_info_email_queue_failed")
        try:
            send_registration_info_email(email)
        except Exception:
            logger.exception("registration_info_email_send_failed")


def _queue_password_reset_email(email: str, reset_link: str) -> None:
    email = (email or "").strip().lower()
    if not email or not reset_link:
        return
    try:
        from apps.notifications.tasks import send_password_reset_email_task

        send_password_reset_email_task.apply_async(
            args=[email, reset_link],
            queue=getattr(settings, "CELERY_EMAIL_QUEUE", "email"),
            retry=False,
        )
    except Exception:
        logger.exception("password_reset_email_queue_failed")
        try:
            send_password_reset_email(email, reset_link)
        except Exception:
            logger.exception("password_reset_email_send_failed")


def _password_reset_rate_limit_key(email: str) -> str:
    return f"pwdreset_rl:{(email or '').strip().lower()}"


def _check_and_track_password_reset_limit(email: str) -> tuple[bool, str]:
    email = (email or "").strip().lower()
    if not email:
        return True, ""
    now = timezone.now()
    key = _password_reset_rate_limit_key(email)
    state = cache.get(key) or {}
    try:
        count = int(state.get("count", 0) or 0)
    except Exception:
        count = 0
    blocked_until_raw = state.get("blocked_until")
    blocked_until = blocked_until_raw if blocked_until_raw else None
    last_sent_raw = state.get("last_sent")
    last_sent = last_sent_raw if last_sent_raw else None

    if blocked_until and now < blocked_until:
        return False, ui_text()["accounts"]["messages"]["pwdreset_requested_later"]

    if count == 1 and last_sent and now < (last_sent + timedelta(minutes=3)):
        return False, ui_text()["accounts"]["messages"]["pwdreset_requested_wait_3m"]

    if count == 2 and last_sent and now < (last_sent + timedelta(minutes=15)):
        return False, ui_text()["accounts"]["messages"]["pwdreset_requested_wait_15m"]

    if count >= 3:
        state["blocked_until"] = now + timedelta(hours=24)
        cache.set(key, state, timeout=60 * 60 * 24)
        return False, ui_text()["accounts"]["messages"]["pwdreset_requested_later"]

    state["count"] = count + 1
    state["last_sent"] = now
    cache.set(key, state, timeout=60 * 60 * 24)
    return True, ""


def _is_reset_token_active(token: str) -> bool:
    token = (token or "").strip()
    if not token:
        return False
    reset = PasswordResetRequest.objects.filter(token=token).first()
    return bool(reset and reset.is_valid)


def _safe_next_url(request) -> str:
    candidate = (
        (request.POST.get("next") or "").strip()
        or (request.GET.get("next") or "").strip()
        or (request.session.get("auth_next") or "").strip()
    )
    if not candidate:
        return ""
    try:
        logout_path = reverse("accounts:logout")
    except Exception:
        logout_path = "/accounts/logout/"
    if url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        try:
            path = urlparse(candidate).path or ""
        except Exception:
            path = ""
        if path == logout_path:
            return ""
        return candidate
    return ""


def _remember_next(request) -> None:
    nxt = (request.GET.get("next") or request.POST.get("next") or "").strip()
    if not nxt:
        return
    if url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        try:
            path = urlparse(nxt).path or ""
        except Exception:
            path = ""
        if path == reverse("accounts:logout"):
            return
        request.session["auth_next"] = nxt


def _htmx_auth_success(request, redirect_to: str = "") -> HttpResponse:
    response = render(request, "accounts/partials/auth_success_oob.html", {})
    response["HX-Trigger"] = "auth-success"
    if redirect_to:
        response["HX-Redirect"] = redirect_to
    return response


def _htmx_close_modal_and_refresh_auth_buttons(request) -> HttpResponse:
    response = render(request, "accounts/partials/auth_success_oob.html", {})
    response["HX-Trigger"] = "auth-success"
    return response


def _public_id_for_user(user) -> int:
    profile, _ = AccountProfile.objects.get_or_create(user=user)
    return int(profile.public_id)


def _redirect_authenticated_to_account(request):
    if not request.user.is_authenticated:
        return None
    nxt = _safe_next_url(request)
    if nxt:
        if _is_htmx(request):
            response = redirect(nxt)
            response["HX-Redirect"] = nxt
            return response
        return redirect(nxt)
    if _is_htmx(request):
        response = redirect("accounts:profile")
        response["HX-Redirect"] = reverse("accounts:profile")
        return response
    return redirect("accounts:profile")


@require_http_methods(["GET"])
def auth_modal_login(request):
    if not _is_htmx(request):
        return redirect("accounts:login")
    _remember_next(request)
    auth_message = ""
    auth_message_kind = ""
    if (request.GET.get("hint") or "").strip() == "balance_requires_login":
        auth_message = "Sign in to pay with your balance."
        auth_message_kind = "error"
    return _render_auth_partial(
        request,
        "accounts/partials/login_content.html",
        {
            "form": LoginForm(),
            "next": _safe_next_url(request),
            "auth_message": auth_message,
            "auth_message_kind": auth_message_kind,
        },
    )


@require_http_methods(["GET"])
def google_oauth_start_view(request):
    _remember_next(request)
    url = build_google_authorize_url(request)
    return redirect(url)


@require_http_methods(["GET"])
def google_oauth_callback_view(request):
    result = handle_google_callback(request)
    if not result.get("ok"):
        messages.error(
            request, ui_text()["accounts"]["messages"]["oauth_google_failed"]
        )
        return redirect("accounts:login")
    if result.get("step_up_required"):
        nxt = _safe_next_url(request)
        if nxt:
            from urllib.parse import quote

            return redirect(f"{reverse('accounts:oauth-step-up')}?next={quote(nxt)}")
        return redirect("accounts:oauth-step-up")
    nxt = _safe_next_url(request)
    if nxt:
        request.session.pop("auth_next", None)
        return redirect(nxt)
    return redirect("accounts:profile")


def _telegram_webapp_origin_allowed(request) -> bool:
    allowed = [
        (o or "").strip().rstrip("/")
        for o in (getattr(settings, "TELEGRAM_WEBAPP_ALLOWED_ORIGINS", None) or [])
        if (o or "").strip()
    ]
    if not allowed:
        return False

    origin = (request.headers.get("Origin") or "").strip()
    if not origin:
        referer = (request.headers.get("Referer") or "").strip()
        if referer:
            try:
                parsed = urlparse(referer)
                if parsed.scheme and parsed.netloc:
                    origin = f"{parsed.scheme}://{parsed.netloc}"
            except Exception:
                origin = ""

    if not origin:
        return bool(settings.DEBUG)

    return origin.rstrip("/") in allowed


def _telegram_webapp_rate_limit_ok(request) -> bool:
    ip = (client_ip_from_request(request) or "").strip() or "unknown"
    key = f"tg_webapp_login_rl:{ip}"
    try:
        count = int(cache.get(key, 0) or 0)
    except Exception:
        count = 0
    if count >= 60:
        return False
    try:
        cache.set(key, count + 1, timeout=3600)
    except Exception:
        pass
    return True


@csrf_exempt
@require_http_methods(["POST"])
def telegram_webapp_auto_login_view(request):
    if not _telegram_webapp_origin_allowed(request):
        logger.warning("telegram_webapp_auto_login_rejected_bad_origin")
        return JsonResponse({"ok": False}, status=403)
    if not _telegram_webapp_rate_limit_ok(request):
        return JsonResponse({"ok": False}, status=429)

    init_data = (request.POST.get("init_data") or "").strip()
    verified, reason, debug_info = verify_telegram_webapp_init_data_detailed(init_data)
    if not verified:
        logger.warning("telegram_webapp_auto_login_failed reason=%s", reason)
        if settings.DEBUG:
            return JsonResponse(
                {"ok": False, "reason": reason, "debug": debug_info}, status=400
            )
        return JsonResponse({"ok": False}, status=400)

    result = upsert_user_from_telegram(request, verified=verified)
    if not result.get("ok"):
        return JsonResponse({"ok": False}, status=400)

    return JsonResponse({"ok": True})


@require_http_methods(["GET"])
def telegram_oidc_start_view(request):
    _remember_next(request)
    url = build_telegram_oidc_authorize_url(request)
    return redirect(url)


@require_http_methods(["GET"])
def telegram_oidc_callback_view(request):
    result = handle_telegram_oidc_callback(request)
    if not result.get("ok"):
        messages.error(
            request, ui_text()["accounts"]["messages"]["oauth_telegram_failed"]
        )
        return redirect("accounts:login")
    nxt = _safe_next_url(request)
    if nxt:
        request.session.pop("auth_next", None)
        return redirect(nxt)
    return redirect("accounts:profile")


@require_http_methods(["GET", "POST"])
def login_view(request):
    already_auth_redirect = _redirect_authenticated_to_account(request)
    if already_auth_redirect:
        return already_auth_redirect
    _remember_next(request)

    if request.method == "POST":
        captcha_required = _turnstile_required_for_login(request)
        if captcha_required and (getattr(settings, "TURNSTILE_SITE_KEY", "") or ""):
            ok, msg = _verify_turnstile_or_error(request)
            if not ok:
                form = LoginForm(request.POST)
                if _is_htmx(request):
                    return _render_auth_partial(
                        request,
                        "accounts/partials/login_content.html",
                        {
                            "form": form,
                            "auth_message": msg,
                            "auth_message_kind": "error",
                            "next": _safe_next_url(request),
                            "captcha_required": True,
                        },
                    )
                messages.error(request, msg)
                return render(
                    request,
                    "accounts/login.html",
                    _auth_full_page_context(
                        {
                            "form": form,
                            "next": _safe_next_url(request),
                            "captcha_required": True,
                            "turnstile_site_key": getattr(
                                settings, "TURNSTILE_SITE_KEY", ""
                            )
                            or "",
                        }
                    ),
                )
        form = LoginForm(request.POST)
        if form.is_valid():
            user = login_with_email_password(
                request,
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
            )
            if user:
                _reset_login_fail(request)
                nxt = _safe_next_url(request)
                if nxt:
                    request.session.pop("auth_next", None)
                if _is_htmx(request):
                    return _htmx_auth_success(request, redirect_to=nxt)
                messages.success(
                    request, ui_text()["accounts"]["messages"]["login_success"]
                )
                return redirect(nxt or "catalog:home")
            new_count = _bump_login_fail(request)
            captcha_now = (getattr(settings, "TURNSTILE_SITE_KEY", "") or "") and (
                new_count
                >= int(getattr(settings, "TURNSTILE_LOGIN_FAIL_THRESHOLD", 3) or 3)
            )
            if _is_htmx(request):
                return _render_auth_partial(
                    request,
                    "accounts/partials/login_content.html",
                    {
                        "form": form,
                        "auth_message": "Invalid email or password.",
                        "auth_message_kind": "error",
                        "next": _safe_next_url(request),
                        "captcha_required": bool(captcha_now),
                    },
                )
            messages.error(request, ui_text()["accounts"]["messages"]["login_failed"])
    else:
        form = LoginForm()

    if _is_htmx(request):
        return _render_auth_partial(
            request,
            "accounts/partials/login_content.html",
            {
                "form": form,
                "next": _safe_next_url(request),
                "captcha_required": bool(
                    (getattr(settings, "TURNSTILE_SITE_KEY", "") or "")
                    and _turnstile_required_for_login(request)
                ),
            },
        )
    return render(
        request,
        "accounts/login.html",
        _auth_full_page_context(
            {
                "form": form,
                "next": _safe_next_url(request),
                "captcha_required": bool(
                    (getattr(settings, "TURNSTILE_SITE_KEY", "") or "")
                    and _turnstile_required_for_login(request)
                ),
                "turnstile_site_key": getattr(settings, "TURNSTILE_SITE_KEY", "") or "",
            }
        ),
    )


@require_http_methods(["GET", "POST"])
def register_view(request):
    already_auth_redirect = _redirect_authenticated_to_account(request)
    if already_auth_redirect:
        return already_auth_redirect
    _remember_next(request)

    if request.method == "POST":
        if getattr(settings, "TURNSTILE_SITE_KEY", "") or "":
            ok, msg = _verify_turnstile_or_error(request)
            if not ok:
                form = RegisterForm(request.POST)
                if _is_htmx(request):
                    return _render_auth_partial(
                        request,
                        "accounts/partials/register_content.html",
                        {
                            "form": form,
                            "auth_message": msg,
                            "auth_message_kind": "error",
                            "next": _safe_next_url(request),
                            "captcha_required": True,
                        },
                    )
                messages.error(request, msg)
                return render(
                    request,
                    "accounts/register.html",
                    _auth_full_page_context(
                        {
                            "form": form,
                            "next": _safe_next_url(request),
                            "captcha_required": True,
                            "turnstile_site_key": getattr(
                                settings, "TURNSTILE_SITE_KEY", ""
                            )
                            or "",
                        }
                    ),
                )
        form = RegisterForm(request.POST)
        if form.is_valid():
            user, _ = register_user(
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
                telegram_handle=form.cleaned_data.get("telegram_handle", ""),
                registration_ip=client_ip_from_request(request),
                request=request,
            )
            _queue_registration_info_email(user.email)
            login_with_email_password(
                request,
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
            )
            nxt = _safe_next_url(request)
            if nxt:
                request.session.pop("auth_next", None)
            if _is_htmx(request):
                return _htmx_auth_success(request, redirect_to=nxt)
            messages.success(
                request, ui_text()["accounts"]["messages"]["register_success"]
            )
            return redirect(nxt or "catalog:home")
        if _is_htmx(request):
            return _render_auth_partial(
                request,
                "accounts/partials/register_content.html",
                {
                    "form": form,
                    "auth_message": "Please fix the errors in the form.",
                    "auth_message_kind": "error",
                    "next": _safe_next_url(request),
                },
            )
    else:
        form = RegisterForm()

    if _is_htmx(request):
        return _render_auth_partial(
            request,
            "accounts/partials/register_content.html",
            {
                "form": form,
                "next": _safe_next_url(request),
                "captcha_required": bool(
                    getattr(settings, "TURNSTILE_SITE_KEY", "") or ""
                ),
            },
        )
    return render(
        request,
        "accounts/register.html",
        _auth_full_page_context(
            {
                "form": form,
                "next": _safe_next_url(request),
                "captcha_required": bool(
                    getattr(settings, "TURNSTILE_SITE_KEY", "") or ""
                ),
                "turnstile_site_key": getattr(settings, "TURNSTILE_SITE_KEY", "") or "",
            }
        ),
    )


@require_http_methods(["POST"])
def logout_view(request):
    logout_current_user(request)
    current_url = (
        request.headers.get("HX-Current-URL") or request.META.get("HTTP_REFERER") or ""
    )
    current_path = ""
    if current_url:
        try:
            current_path = urlparse(current_url).path or ""
        except Exception:
            current_path = ""
    redirect_home = bool(current_path.startswith("/accounts/"))

    if _is_htmx(request):
        response = render(request, "accounts/partials/auth_success_oob.html", {})
        response["HX-Trigger"] = "auth-success"
        if redirect_home:
            response["HX-Redirect"] = reverse("catalog:home")
        return response
    messages.success(request, ui_text()["accounts"]["messages"]["logout_success"])
    if redirect_home:
        return redirect("catalog:home")
    if current_url and url_has_allowed_host_and_scheme(
        current_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(current_url)
    return redirect("catalog:home")


@require_http_methods(["GET", "POST"])
def password_reset_request_view(request):
    already_auth_redirect = _redirect_authenticated_to_account(request)
    if already_auth_redirect:
        return already_auth_redirect

    if request.method == "POST":
        if getattr(settings, "TURNSTILE_SITE_KEY", "") or "":
            ok, msg = _verify_turnstile_or_error(request)
            if not ok:
                form = PasswordResetRequestForm(request.POST)
                if _is_htmx(request):
                    return _render_auth_partial(
                        request,
                        "accounts/partials/password_reset_request_content.html",
                        {
                            "form": form,
                            "auth_message": msg,
                            "auth_message_kind": "error",
                            "captcha_required": True,
                        },
                    )
                messages.error(request, msg)
                return render(
                    request,
                    "accounts/password_reset_request.html",
                    _auth_full_page_context(
                        {
                            "form": form,
                            "captcha_required": True,
                            "turnstile_site_key": getattr(
                                settings, "TURNSTILE_SITE_KEY", ""
                            )
                            or "",
                        }
                    ),
                )
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email_norm = (form.cleaned_data.get("email") or "").strip().lower()
            rate_ok, rate_msg = _check_and_track_password_reset_limit(email_norm)
            if not rate_ok:
                if _is_htmx(request):
                    return _render_auth_partial(
                        request,
                        "accounts/partials/password_reset_request_content.html",
                        {
                            "form": form,
                            "auth_message": rate_msg,
                            "auth_message_kind": "error",
                            "captcha_required": True,
                        },
                    )
                messages.error(request, rate_msg)
                return redirect("accounts:password-reset-request")
            serializer = PasswordResetRequestSerializer(data=form.cleaned_data)
            serializer.is_valid(raise_exception=True)
            reset_obj = serializer.save()
            if reset_obj:
                reset_link = request.build_absolute_uri(
                    f"{reverse('accounts:password-reset-confirm')}?token={reset_obj.token}"
                )
                _queue_password_reset_email(reset_obj.email_snapshot, reset_link)
            if _is_htmx(request):
                msg = ui_text()["accounts"]["messages"]["pwdreset_requested"]
                return _render_auth_partial(
                    request,
                    "accounts/partials/password_reset_request_content.html",
                    {
                        "form": PasswordResetRequestForm(),
                        "auth_message": msg,
                        "auth_message_kind": "success",
                        "captcha_required": True,
                    },
                )
            messages.success(
                request,
                ui_text()["accounts"]["messages"]["pwdreset_requested"],
            )
            return redirect("accounts:password-reset-request")
    else:
        form = PasswordResetRequestForm()

    if _is_htmx(request):
        return _render_auth_partial(
            request,
            "accounts/partials/password_reset_request_content.html",
            {
                "form": form,
                "captcha_required": bool(
                    getattr(settings, "TURNSTILE_SITE_KEY", "") or ""
                ),
            },
        )
    return render(
        request,
        "accounts/password_reset_request.html",
        _auth_full_page_context(
            {
                "form": form,
                "captcha_required": bool(
                    getattr(settings, "TURNSTILE_SITE_KEY", "") or ""
                ),
                "turnstile_site_key": getattr(settings, "TURNSTILE_SITE_KEY", "") or "",
            }
        ),
    )


@require_http_methods(["GET", "POST"])
def password_reset_confirm_view(request):
    already_auth_redirect = _redirect_authenticated_to_account(request)
    if already_auth_redirect:
        return already_auth_redirect

    if request.method == "GET":
        token = request.GET.get("token", "")
        if token:
            if _is_reset_token_active(token):
                request.session[PASSWORD_RESET_TOKEN_SESSION_KEY] = token
            else:
                request.session.pop(PASSWORD_RESET_TOKEN_SESSION_KEY, None)

    if request.method == "POST":
        form = PasswordResetConfirmForm(request.POST)
        if form.is_valid():
            token = (request.POST.get("token") or "").strip() or (
                request.session.get(PASSWORD_RESET_TOKEN_SESSION_KEY) or ""
            ).strip()
            if not token or not _is_reset_token_active(token):
                request.session.pop(PASSWORD_RESET_TOKEN_SESSION_KEY, None)
                if _is_htmx(request):
                    return _render_auth_partial(
                        request,
                        "accounts/partials/password_reset_confirm_content.html",
                        {
                            "form": form,
                            "reset_token": "",
                            "can_submit": False,
                            "auth_message": ui_text()["accounts"]["messages"][
                                "pwdreset_link_invalid"
                            ],
                            "auth_message_kind": "error",
                        },
                    )
                messages.error(
                    request, ui_text()["accounts"]["messages"]["pwdreset_link_invalid"]
                )
                return redirect("accounts:password-reset-request")
            serializer = PasswordResetConfirmSerializer(
                data={
                    "token": token,
                    "password": form.cleaned_data["password"],
                }
            )
            if serializer.is_valid():
                user = serializer.save()
            else:
                user = None
            if user:
                request.session.pop(PASSWORD_RESET_TOKEN_SESSION_KEY, None)
                login(request, user)
                if _is_htmx(request):
                    return _htmx_auth_success(
                        request, redirect_to=reverse("accounts:profile")
                    )
                messages.success(
                    request, ui_text()["accounts"]["messages"]["pwdreset_done_login"]
                )
                return redirect("accounts:profile")
            if _is_htmx(request):
                return _render_auth_partial(
                    request,
                    "accounts/partials/password_reset_confirm_content.html",
                    {
                        "form": form,
                        "reset_token": "",
                        "can_submit": False,
                        "auth_message": ui_text()["accounts"]["messages"][
                            "pwdreset_link_invalid"
                        ],
                        "auth_message_kind": "error",
                    },
                )
            messages.error(
                request, ui_text()["accounts"]["messages"]["pwdreset_link_invalid"]
            )
    else:
        form = PasswordResetConfirmForm()

    reset_token = (request.session.get(PASSWORD_RESET_TOKEN_SESSION_KEY) or "").strip()
    has_token = bool(reset_token) and _is_reset_token_active(reset_token)
    if not has_token and reset_token:
        request.session.pop(PASSWORD_RESET_TOKEN_SESSION_KEY, None)
        reset_token = ""
    if _is_htmx(request):
        return _render_auth_partial(
            request,
            "accounts/partials/password_reset_confirm_content.html",
            {
                "form": form,
                "reset_token": reset_token,
                "can_submit": has_token,
                "auth_message": ""
                if has_token
                else ui_text()["accounts"]["messages"]["pwdreset_link_invalid"],
                "auth_message_kind": "error",
            },
        )
    return render(
        request,
        "accounts/password_reset_confirm.html",
        _auth_full_page_context(
            {
                "form": form,
                "reset_token": reset_token,
                "can_submit": has_token,
                "auth_message": ""
                if has_token
                else ui_text()["accounts"]["messages"]["pwdreset_link_invalid"],
                "auth_message_kind": "error",
            }
        ),
    )


@require_http_methods(["GET", "POST"])
def oauth_step_up_view(request):
    _remember_next(request)
    if request.method == "POST":
        form = OAuthStepUpForm(request.POST)
        if form.is_valid():
            user = verify_oauth_step_up(request, form.cleaned_data["password"])
            if user:
                nxt = _safe_next_url(request)
                if nxt:
                    request.session.pop("auth_next", None)
                if _is_htmx(request):
                    return _htmx_auth_success(request, redirect_to=nxt)
                messages.success(
                    request, ui_text()["accounts"]["messages"]["stepup_success"]
                )
                return redirect(nxt or "catalog:home")
            if _is_htmx(request):
                return _render_auth_partial(
                    request,
                    "accounts/partials/oauth_step_up_content.html",
                    {
                        "form": form,
                        "auth_message": "Invalid password.",
                        "auth_message_kind": "error",
                        "next": _safe_next_url(request),
                    },
                )
            messages.error(
                request, ui_text()["accounts"]["messages"]["stepup_invalid_password"]
            )
    else:
        form = OAuthStepUpForm()

    if _is_htmx(request):
        return _render_auth_partial(
            request,
            "accounts/partials/oauth_step_up_content.html",
            {"form": form, "next": _safe_next_url(request)},
        )
    return render(
        request,
        "accounts/oauth_step_up.html",
        _auth_full_page_context(
            {
                "form": form,
                "is_htmx": False,
                "next": _safe_next_url(request),
            }
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def account_profile_view(request):
    profile, _ = AccountProfile.objects.get_or_create(user=request.user)

    profile_form = ProfileUpdateForm(
        initial={
            "first_name": request.user.first_name or "",
            "last_name": request.user.last_name or "",
            "telegram_handle": profile.telegram_handle or "",
        }
    )
    password_form = PasswordChangeFromProfileForm(user=request.user)
    password_set_form = PasswordSetFromGoogleForm()
    can_set_password = (
        not request.user.has_usable_password()
    ) and request.user.account_identities.filter(provider="google").exists()
    has_telegram_identity = request.user.account_identities.filter(
        provider="telegram"
    ).exists()

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "profile_update":
            profile_form = ProfileUpdateForm(request.POST)
            if profile_form.is_valid():
                request.user.first_name = profile_form.cleaned_data["first_name"]
                request.user.last_name = profile_form.cleaned_data["last_name"]
                request.user.save(update_fields=["first_name", "last_name"])

                profile.telegram_handle = profile_form.cleaned_data["telegram_handle"]
                profile.save(update_fields=["telegram_handle", "updated_at"])

                messages.success(
                    request, ui_text()["accounts"]["messages"]["profile_updated"]
                )
                return redirect("accounts:profile")
            messages.error(
                request, ui_text()["accounts"]["messages"]["form_fix_errors"]
            )

        elif action == "password_change":
            if has_telegram_identity:
                messages.error(
                    request, "Password change is unavailable for Telegram accounts."
                )
                return redirect("accounts:profile")
            password_form = PasswordChangeFromProfileForm(
                request.POST, user=request.user
            )
            if password_form.is_valid():
                request.user.set_password(password_form.cleaned_data["new_password"])
                request.user.save(update_fields=["password"])
                update_session_auth_hash(request, request.user)
                messages.success(request, "Password updated.")
                return redirect("accounts:profile")
            messages.error(
                request, ui_text()["accounts"]["messages"]["form_fix_errors"]
            )

        elif action == "password_set_google":
            if has_telegram_identity:
                messages.error(
                    request, "Setting a password is unavailable for Telegram accounts."
                )
                return redirect("accounts:profile")
            if not can_set_password:
                messages.error(request, "Unknown action.")
            else:
                password_set_form = PasswordSetFromGoogleForm(request.POST)
                if password_set_form.is_valid():
                    request.user.set_password(
                        password_set_form.cleaned_data["new_password"]
                    )
                    request.user.save(update_fields=["password"])
                    update_session_auth_hash(request, request.user)
                    messages.success(request, "Password set.")
                    return redirect("accounts:profile")
                messages.error(
                    request, ui_text()["accounts"]["messages"]["form_fix_errors"]
                )

        else:
            messages.error(request, ui_text()["accounts"]["messages"]["unknown_action"])

    context = {
        "profile": profile,
        "profile_form": profile_form,
        "password_form": password_form,
        "password_set_form": password_set_form,
        "can_set_password": can_set_password,
        "has_telegram_identity": has_telegram_identity,
    }
    return render(request, "accounts/profile.html", context)


@login_required
@require_http_methods(["GET"])
def account_orders_view(request):
    from django.core.paginator import Paginator
    from django.urls import reverse

    from apps.catalog.sku_display import build_selected_sku_rows
    from apps.orders.models import Order

    profile, _ = AccountProfile.objects.get_or_create(user=request.user)
    cancelled_completed = [Order.Status.CANCELLED, Order.Status.COMPLETED]

    base_qs = (
        Order.objects.filter(user_id=request.user.pk)
        .prefetch_related("items__product__product_card")
        .only("id", "public_id", "status", "total", "currency", "created_at")
        .order_by("-created_at")
    )

    active_qs = base_qs.exclude(status__in=cancelled_completed)[:20]
    history_qs = base_qs.filter(status__in=cancelled_completed)

    def _order_title(o: Order) -> str:
        try:
            first_item = next(iter(getattr(o, "items", []).all()))
        except Exception:
            first_item = None
        product = getattr(first_item, "product", None)
        card = getattr(product, "product_card", None) if product else None
        base_title = str(getattr(card, "name", "") or "").strip()
        if not base_title:
            base_title = f"Order {o.public_id}"

        if not product or not first_item:
            return base_title

        try:
            selection_rows = build_selected_sku_rows(
                product_id=int(getattr(product, "id", 0) or 0),
                price=getattr(first_item, "unit_price", None),
                attributes=getattr(product, "attributes", None) or {},
                selector_axes=getattr(card, "selector_axes", None) or [],
                ui_labels=getattr(card, "ui_labels", None) or {},
            )
        except Exception:
            selection_rows = []

        values = [str(r.get("value") or "").strip() for r in (selection_rows or [])]
        values = [v for v in values if v]
        if values:
            return " / ".join([base_title, *values])
        return base_title

    def _status_badge_class(o: Order) -> str:
        s = str(o.status or "")
        if s == Order.Status.COMPLETED:
            return "status-completed"
        if s == Order.Status.CANCELLED:
            return "status-cancelled"
        if s == Order.Status.AWAITING_PAYMENT:
            return "status-awaiting-payment"
        if s == Order.Status.WAITING_STOCK:
            return "status-waiting-stock"
        if s == Order.Status.PARTIALLY_FULFILLED:
            return "status-partially-fulfilled"
        if s == Order.Status.MANUAL_PENDING:
            return "status-manual-pending"
        if s == Order.Status.PAID:
            return "status-paid-ok"
        return "status-awaiting-payment"

    def _pack(o: Order) -> dict:
        return {
            "public_id": o.public_id,
            "title": _order_title(o),
            "total": o.total,
            "currency": o.currency,
            "created_at": o.created_at,
            "status_label": o.get_status_display(),
            "status_badge_class": _status_badge_class(o),
            "url": reverse("orders-web:order-page", kwargs={"public_id": o.public_id}),
        }

    context = {
        "profile": profile,
        "active_orders": [_pack(o) for o in active_qs],
        "history_page": Paginator(history_qs, 20).get_page(
            (request.GET.get("hist_page") or "").strip() or "1"
        ),
    }
    context["history_orders"] = [_pack(o) for o in context["history_page"].object_list]
    return render(request, "accounts/orders.html", context)


@login_required
@require_http_methods(["GET"])
def account_balance_view(request):
    from apps.core.ui_text import PROVIDER_UI_LABELS
    from apps.payments.internal_balance import internal_balance_channel_info
    from apps.payments.models import Payment, WalletTransaction
    from apps.payments.providers.registry import get_topup_provider_buttons

    profile, _ = AccountProfile.objects.get_or_create(user=request.user)
    payment_providers = get_topup_provider_buttons()

    raw_next = (request.GET.get("next") or "").strip()
    balance_topup_next = raw_next if _safe_internal_path(request, raw_next) else ""

    tx_qs = (
        WalletTransaction.objects.filter(user_id=request.user.pk)
        .order_by("-created_at")
        .only(
            "id",
            "kind",
            "source_type",
            "source_id",
            "amount",
            "currency",
            "description",
            "created_at",
            "metadata",
        )
    )
    tx_page = Paginator(tx_qs, 20).get_page(
        (request.GET.get("tx_page") or "").strip() or "1"
    )
    tx_rows = list(tx_page.object_list)

    payment_source_ids = [
        str(row.source_id)
        for row in tx_rows
        if str(row.source_type) == str(WalletTransaction.SourceType.PAYMENT)
    ]
    payments_map = {
        str(row.id): row
        for row in Payment.objects.filter(id__in=payment_source_ids).only(
            "id", "provider_payment_id", "provider"
        )
    }

    kind_map = {
        WalletTransaction.Kind.TOPUP_CREDIT: "Top-up",
        WalletTransaction.Kind.ORDER_DEBIT: "Order payment",
        WalletTransaction.Kind.REFUND_CREDIT: "Refund",
        WalletTransaction.Kind.CHARGEBACK_DEBIT: "Chargeback",
        WalletTransaction.Kind.MANUAL_ADJUSTMENT: "Manual adjustment",
    }
    for row in tx_rows:
        row.display_kind = kind_map.get(row.kind, row.get_kind_display())
        meta = row.metadata if isinstance(row.metadata, dict) else {}
        if row.kind == WalletTransaction.Kind.ORDER_DEBIT:
            row.display_description = (
                f"Order payment {meta.get('order_public_id')}"
                if meta.get("order_public_id")
                else (row.description or "Order payment")
            )
        elif row.kind == WalletTransaction.Kind.TOPUP_CREDIT:
            row.display_description = (
                f"Balance top-up {meta.get('balance_top_up_public_id')}"
                if meta.get("balance_top_up_public_id")
                else (row.description or "Balance top-up")
            )
        elif row.kind == WalletTransaction.Kind.REFUND_CREDIT:
            row.display_description = (
                f"Refund for order {meta.get('order_public_id')}"
                if meta.get("order_public_id")
                else (row.description or "Refund")
            )
        else:
            row.display_description = row.description or "Balance operation"

        payment = payments_map.get(str(row.source_id))
        provider_key = (
            str(getattr(payment, "provider", "") or "").strip().lower()
            or str(meta.get("provider") or "").strip().lower()
        )
        if provider_key == "site_balance":
            row.provider_label = "Site balance"
        else:
            row.provider_label = PROVIDER_UI_LABELS.get(provider_key, provider_key or "-")

    context = {
        "profile": profile,
        "payment_providers": payment_providers,
        "internal_balance_channel": internal_balance_channel_info(
            balance=profile.balance
        ),
        "wallet_transactions": tx_rows,
        "wallet_tx_page": tx_page,
        "balance_topup_next": balance_topup_next,
    }
    return render(request, "accounts/balance.html", context)


@login_required
@require_http_methods(["GET"])
def account_balance_topup_result_view(request):
    state = (request.GET.get("topup") or "").strip().lower()
    if state not in ("success", "cancel"):
        return redirect("accounts:balance")

    return_path = request.session.pop(_BALANCE_TOPUP_RETURN_SESSION_KEY, None)
    if (
        not isinstance(return_path, str)
        or not return_path.startswith("/")
        or return_path.startswith("//")
    ):
        return_path = "/"
    elif not _safe_internal_path(request, return_path):
        return_path = "/"

    context = {
        "topup_result_state": state,
        "continue_url": return_path,
    }
    return render(request, "accounts/balance_topup_result.html", context)


@login_required
@require_http_methods(["POST"])
def account_balance_topup_start_view(request):
    from decimal import Decimal, InvalidOperation

    from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
    from rest_framework.exceptions import ValidationError as DRFValidationError

    from apps.payments.services import init_balance_topup_payment

    post_next = (request.POST.get("next") or "").strip()

    provider = (request.POST.get("provider") or "").strip().lower()
    raw_amount = (request.POST.get("amount") or "").strip().replace(",", ".")
    try:
        amount = Decimal(raw_amount)
    except InvalidOperation:
        messages.error(request, "Enter a valid amount.")
        return _redirect_to_balance_form(request, post_next)

    request.session[_BALANCE_TOPUP_RETURN_SESSION_KEY] = (
        _resolve_balance_topup_return_path(request, post_next)
    )

    try:
        payment = init_balance_topup_payment(
            user=request.user,
            amount=amount,
            currency="USD",
            provider_name=provider,
        )
    except DRFValidationError as exc:
        detail = exc.detail
        if isinstance(detail, dict):
            parts = []
            for k, v in detail.items():
                if isinstance(v, list):
                    parts.append(f"{k}: {v[0]}")
                else:
                    parts.append(f"{k}: {v}")
            messages.error(request, " ".join(parts) if parts else "Invalid input.")
        else:
            messages.error(request, str(detail))
        return _redirect_to_balance_form(request, post_next)
    except DRFPermissionDenied:
        messages.error(request, "Not allowed.")
        return _redirect_to_balance_form(request, post_next)
    except RuntimeError as exc:
        messages.error(request, str(exc))
        return _redirect_to_balance_form(request, post_next)

    if not payment.invoice_url:
        messages.error(
            request,
            "Payment provider did not return a checkout URL. Check API keys and NOWPayments status.",
        )
        return _redirect_to_balance_form(request, post_next)

    return redirect(payment.invoice_url)


@login_required
@require_http_methods(["POST"])
def account_set_email_once_view(request):
    if (request.user.email or "").strip():
        return HttpResponse(status=204)

    form = SetEmailOnceForm(request.POST, user=request.user)
    if not form.is_valid():
        return HttpResponse(status=409)

    request.user.email = form.cleaned_data["email"]
    request.user.save(update_fields=["email"])
    return HttpResponse(status=204)


class RegisterAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_register"

    def post(self, request):
        serializer = RegisterSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {"public_id": _public_id_for_user(user), "email": user.email},
            status=status.HTTP_201_CREATED,
        )


class LoginAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_login"

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = login_with_email_password(
            request,
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        if not user:
            return Response(
                {"detail": "Invalid email or password."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"public_id": _public_id_for_user(user), "email": user.email})


class LogoutAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logout_current_user(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetRequestAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_password_reset"

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email_norm = (serializer.validated_data.get("email") or "").strip().lower()
        rate_ok, _rate_msg = _check_and_track_password_reset_limit(email_norm)
        detail = ui_text()["accounts"]["messages"]["pwdreset_requested"]
        if not rate_ok:
            return Response({"detail": detail}, status=status.HTTP_200_OK)
        reset_obj = serializer.save()
        if reset_obj:
            reset_link = request.build_absolute_uri(
                f"{reverse('accounts:password-reset-confirm')}?token={reset_obj.token}"
            )
            _queue_password_reset_email(reset_obj.email_snapshot, reset_link)
        return Response({"detail": detail}, status=status.HTTP_200_OK)


class PasswordResetConfirmAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_password_reset_confirm"

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"detail": "Could not update password."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = serializer.save()
        if not user:
            return Response(
                {"detail": "Could not update password."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"detail": "Password updated."})


class AccountMeAPIView(generics.RetrieveUpdateAPIView):
    serializer_class = AccountMeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        AccountProfile.objects.get_or_create(user=self.request.user)
        return self.request.user
