from __future__ import annotations

from .services import ensure_profile
from .tracking import apply_session_tracking


class AccountsTrackingMiddleware:
    """
    Lightweight marketing/session tracking for MVP:
    - persists UTM parameters into session
    - updates AccountProfile.last_active + session context for authenticated users
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        utm_updates = {}
        for k, v in request.GET.items():
            if not k.startswith("utm_"):
                continue
            value = (v or "").strip()
            if value:
                utm_updates[k] = value

        if utm_updates:
            current = request.session.get("utm_params") or {}
            if not isinstance(current, dict):
                current = {}
            current.update(utm_updates)
            request.session["utm_params"] = current

        response = self.get_response(request)

        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            profile = ensure_profile(request.user)
            apply_session_tracking(profile, request)

        return response
