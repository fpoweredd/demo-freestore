from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


def terms_view(request: HttpRequest) -> HttpResponse:
    template = "legal/terms_content.html" if _is_htmx(request) else "legal/terms.html"
    response = render(request, template)
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


def policy_view(request: HttpRequest) -> HttpResponse:
    template = "legal/policy_content.html" if _is_htmx(request) else "legal/policy.html"
    response = render(request, template)
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


def contacts_view(request: HttpRequest) -> HttpResponse:
    template = (
        "legal/contacts_content.html" if _is_htmx(request) else "legal/contacts.html"
    )
    return render(request, template)


def robots_txt_view(_request: HttpRequest) -> HttpResponse:
    content = "\n".join(
        [
            "User-agent: *",
            "Disallow: /policy/",
            "Disallow: /terms/",
            "",
        ]
    )
    return HttpResponse(content, content_type="text/plain; charset=utf-8")
