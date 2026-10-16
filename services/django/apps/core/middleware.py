from __future__ import annotations

from django.shortcuts import render
from django.urls import reverse

from .services import get_shop_settings


class MaintenanceModeMiddleware:
    """
    Global maintenance guard for storefront pages.
    Allows admin/auth/health/static paths.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            settings = get_shop_settings()
        except Exception:
            settings = None
        if settings and settings.maintenance_mode:
            path = request.path or "/"
            allowed_prefixes = (
                reverse("admin:index"),
                "/accounts/",
                "/api/",
                "/health/",
                "/healthz",
                "/readyz",
                "/static/",
                "/media/",
                "/webhooks/",
            )
            if not path.startswith(allowed_prefixes):
                return render(request, "core/maintenance.html", status=503)
        return self.get_response(request)
