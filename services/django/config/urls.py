import logging

from apps.core.views_errors import preview_page_not_found
from apps.core.views_legal import (
    contacts_view,
    policy_view,
    robots_txt_view,
    terms_view,
)
from apps.orders.views_bot_internal import ManualOrderTelegramCompleteView
from apps.payments.views import (
    EnotWebhookAPIView,
    NowPaymentsWebhookAPIView,
    RollyPayWebhookAPIView,
)
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path, re_path
from django.views.static import serve

admin.site.site_header = "Admin"
admin.site.site_title = "Admin"
admin.site.index_title = "Admin"

logger = logging.getLogger(__name__)


def healthcheck(_request):
    return JsonResponse({"status": "ok"})


def readiness(_request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        cache.set("readyz", "1", timeout=5)
        _ = cache.get("readyz")
    except Exception:
        logger.exception("readiness_check_failed")
        return JsonResponse(
            {"status": "error", "detail": "unavailable"},
            status=503,
        )
    return JsonResponse({"status": "ready"})


urlpatterns = [
    path(
        "internal/bot/manual-orders/complete/",
        ManualOrderTelegramCompleteView.as_view(),
        name="bot-manual-order-complete",
    ),
    path("admin/", admin.site.urls),
    path("robots.txt", robots_txt_view, name="robots-txt"),
    path("health/", healthcheck, name="health"),
    path("healthz", healthcheck, name="healthz"),
    path("readyz", readiness, name="readyz"),
    path("", include(("apps.orders.web_urls", "orders-web"), namespace="orders-web")),
    path("", include(("apps.catalog.urls", "catalog"), namespace="catalog")),
    path("", include(("apps.accounts.urls", "accounts"), namespace="accounts")),
    path("api/v1/", include("apps.catalog.api_urls")),
    path(
        "api/v1/",
        include(("apps.accounts.api_urls", "accounts-api"), namespace="accounts-api"),
    ),
    path("api/v1/", include("apps.orders.urls")),
    path("api/v1/", include("apps.payments.urls")),
    path(
        "webhooks/nowpayments",
        NowPaymentsWebhookAPIView.as_view(),
        name="nowpayments-webhook-no-slash",
    ),
    path(
        "webhooks/nowpayments/",
        NowPaymentsWebhookAPIView.as_view(),
        name="nowpayments-webhook",
    ),
    path(
        "webhooks/rollypay",
        RollyPayWebhookAPIView.as_view(),
        name="rollypay-webhook-no-slash",
    ),
    path(
        "webhooks/rollypay/",
        RollyPayWebhookAPIView.as_view(),
        name="rollypay-webhook",
    ),
    path(
        "webhooks/enot",
        EnotWebhookAPIView.as_view(),
        name="enot-webhook-no-slash",
    ),
    path(
        "webhooks/enot/",
        EnotWebhookAPIView.as_view(),
        name="enot-webhook",
    ),
    path(
        "terms/",
        terms_view,
        name="terms",
    ),
    path(
        "policy/",
        policy_view,
        name="policy",
    ),
    path(
        "contacts/",
        contacts_view,
        name="contacts",
    ),
]

if settings.DEBUG:
    urlpatterns.insert(
        0,
        path(
            "__preview/404/",
            preview_page_not_found,
            name="preview-404",
        ),
    )
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # Without e.g. nginx / S3: serve public uploads from MEDIA_ROOT (same role as nginx `location /media`).
    media_url = settings.MEDIA_URL.lstrip("/")
    if media_url:
        urlpatterns += [
            re_path(
                rf"^{media_url}(?P<path>.*)$",
                serve,
                {"document_root": settings.MEDIA_ROOT},
            )
        ]

handler404 = "apps.core.views_errors.page_not_found"
