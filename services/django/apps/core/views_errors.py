"""Custom HTTP error pages."""

from django.conf import settings
from django.http import HttpResponseNotFound
from django.shortcuts import render


def page_not_found(request, exception):
    """Registered as handler404; called only when DEBUG is False."""
    return render(
        request,
        "errors/404.html",
        {
            "is_preview": False,
        },
        status=404,
    )


def preview_page_not_found(request):
    """
    Dev-only: same markup as production 404 so designers can open it while DEBUG=True.
    """
    if not settings.DEBUG:
        return HttpResponseNotFound()
    return render(
        request,
        "errors/404.html",
        {
            "is_preview": True,
        },
        status=404,
    )
