from __future__ import annotations

from decimal import Decimal

_DEFAULT_AXIS_LABELS = {
    "region": "Region",
    "nominal": "Denomination",
    "variant": "Variant",
    "platform": "Platform",
    "sku": "SKU",
    "option": "Option",
}

_LEGACY_AXIS_KEYS = ("region", "nominal")


def _format_price(value) -> str:
    if value is None:
        return "0"
    amount = Decimal(str(value))
    if amount == amount.to_integral_value():
        return str(int(amount))
    return f"{amount:.2f}"


def _normalize_selector_axes(selector_axes) -> list[str]:
    if not isinstance(selector_axes, list):
        return []
    out: list[str] = []
    for raw in selector_axes:
        if isinstance(raw, dict):
            key = str(raw.get("key") or "").strip().lower()
        else:
            key = str(raw or "").strip().lower()
        if not key or key in out:
            continue
        out.append(key)
    return out


def _axis_label(key: str, ui_labels: dict | None) -> str:
    labels = ui_labels if isinstance(ui_labels, dict) else {}
    custom = labels.get(key)
    if custom is not None and str(custom).strip():
        return str(custom).strip()
    return _DEFAULT_AXIS_LABELS.get(key) or key.replace("_", " ").title()


def _attr_value(attributes: dict, key: str) -> str:
    if not isinstance(attributes, dict):
        return ""
    needle = str(key or "").strip().lower()
    if not needle:
        return ""
    for raw_key, raw_value in attributes.items():
        if str(raw_key or "").strip().lower() != needle:
            continue
        text = str(raw_value or "").strip()
        if text:
            return text
    return ""


def build_selected_sku_rows(
    *,
    product_id: int,
    price,
    attributes: dict | None,
    selector_axes: list | None = None,
    ui_labels: dict | None = None,
) -> list[dict[str, str]]:
    """
    Human-readable SKU rows for order/account views.
    Uses ProductCard.selector_axes order, then remaining attribute keys.
    Product id (#N) is shown only when axis "variant" is configured explicitly.
    """
    attrs = attributes if isinstance(attributes, dict) else {}
    axes = _normalize_selector_axes(selector_axes)
    labels = ui_labels if isinstance(ui_labels, dict) else {}
    rows: list[dict[str, str]] = []
    used_keys: set[str] = set()

    def _append_row(*, key: str, label: str, value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        rows.append({"label": label, "value": text})
        used_keys.add(key)

    for axis_key in axes:
        if axis_key == "variant":
            _append_row(
                key="variant",
                label=_axis_label("variant", labels),
                value=f"#{int(product_id)}",
            )
            continue
        value = _attr_value(attrs, axis_key)
        if value:
            _append_row(
                key=axis_key,
                label=_axis_label(axis_key, labels),
                value=value,
            )

    for legacy_key in _LEGACY_AXIS_KEYS:
        if legacy_key in used_keys:
            continue
        value = _attr_value(attrs, legacy_key)
        if value:
            _append_row(
                key=legacy_key,
                label=_axis_label(legacy_key, labels),
                value=value,
            )

    remaining_keys = sorted(
        str(k).strip().lower()
        for k in attrs.keys()
        if str(k or "").strip() and str(k).strip().lower() not in used_keys
    )
    for key in remaining_keys:
        value = _attr_value(attrs, key)
        if value:
            _append_row(key=key, label=_axis_label(key, labels), value=value)

    if not rows:
        rows.append(
            {
                "label": _axis_label("variant", labels),
                "value": f"#{int(product_id)}",
            }
        )
    return rows


def sku_row_values(rows: list[dict[str, str]] | None) -> list[str]:
    values: list[str] = []
    for row in rows or []:
        text = str(row.get("value") or "").strip()
        if text:
            values.append(text)
    return values
