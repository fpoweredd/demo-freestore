from __future__ import annotations

from .ui_text import ui_text
from .services import get_shop_settings


def ui(request):
    return {"ui": ui_text()}


def catalog_search_extras(request):
    """Preserve catalog ?tag= when submitting search from the header form."""
    rm = getattr(request, "resolver_match", None)
    ns = getattr(rm, "namespace", None) if rm else None
    url_name = getattr(rm, "url_name", None) if rm else None
    tag = ""
    if rm and ns == "catalog" and url_name == "home":
        tag = (request.GET.get("tag") or "").strip()
    return {"catalog_filter_tag": tag}


def shop_runtime_flags(_request):
    try:
        cfg = get_shop_settings()
        return {
            "shop_maintenance_mode": bool(cfg.maintenance_mode),
            "shop_buy_enabled": bool(cfg.buy_enabled),
            "shop_refill_enabled": bool(cfg.refill_enabled),
        }
    except Exception:
        return {
            "shop_maintenance_mode": False,
            "shop_buy_enabled": True,
            "shop_refill_enabled": True,
        }
