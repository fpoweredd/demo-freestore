from __future__ import annotations

from html import escape


def _value_or_dash(value: str | None) -> str:
    return (value or "").strip() or "-"


def _tg_username_text(value: str | None) -> str:
    normalized = _value_or_dash(value)
    if normalized == "-":
        return normalized
    return normalized if normalized.startswith("@") else f"@{normalized}"


def build_manual_order_notification_html(
    *,
    order_public_id: int,
    user_public_id: str | None,
    user_email: str | None,
    order_email: str | None,
    guest_email: str | None,
    total_rub: str,
    payment_method: str | None,
    wallet_balance_after_rub: str | None,
    tg_auth: str | None,
    tg_handler: str | None,
    role: str | None,
    reg_geo: str | None,
    locale: str | None,
    utm_params: dict[str, str],
    items: list[dict],
    headline_html: str = "<b>🛠 Manual order</b>",
) -> str:
    normalized_user_public_id = _value_or_dash(user_public_id)
    normalized_user_email = _value_or_dash(user_email)
    normalized_order_email = _value_or_dash(order_email)
    normalized_guest_email = _value_or_dash(guest_email)

    if normalized_user_public_id == "-" and normalized_guest_email != "-":
        email_line = f"Guest email: <code>{escape(normalized_guest_email)}</code>"
    elif (
        normalized_user_email != "-"
        and normalized_order_email != "-"
        and normalized_user_email.lower() == normalized_order_email.lower()
    ):
        email_line = f"Email: <code>{escape(normalized_order_email)}</code>"
    else:
        email_line = (
            f"User email: <code>{escape(normalized_user_email)}</code>\n"
            f"Order email: <code>{escape(normalized_order_email)}</code>"
        )

    lines: list[str] = [
        headline_html,
        f"Order ID: <code>{order_public_id}</code>",
        f"User public id: <code>{escape(normalized_user_public_id)}</code>",
        "",
        email_line,
    ]

    if _value_or_dash(tg_auth) != "-":
        lines.append(f"TG AUTH: {escape(_tg_username_text(tg_auth))}")
    elif _value_or_dash(tg_handler) != "-":
        lines.append(f"TG Handler: {escape(_tg_username_text(tg_handler))}")

    lines.extend(["", "<b>Позиции:</b>"])

    for item in items:
        product_name = _value_or_dash(str(item.get("product_name", "") or ""))
        quantity = int(item.get("quantity") or 1)
        sku_line = _value_or_dash(str(item.get("sku_line", "") or ""))
        title = sku_line if sku_line != "-" else product_name
        lines.append(f"{escape(title)} x{quantity}")
        labeled_params = item.get("sku_params_labeled") or []
        if isinstance(labeled_params, list) and labeled_params:
            for row in labeled_params:
                if not isinstance(row, dict):
                    continue
                label = str(row.get("label") or row.get("key") or "").strip()
                value = str(row.get("value") or "").strip()
                if label and value:
                    lines.append(f"- {escape(label)}: <code>{escape(value)}</code>")
            continue

        sku_params = item.get("sku_params") or {}
        if isinstance(sku_params, dict) and sku_params:
            for key in sorted(sku_params.keys()):
                value = str(sku_params.get(key) or "").strip()
                if value:
                    lines.append(
                        f"- <code>{escape(str(key))}</code>: <code>{escape(value)}</code>"
                    )

    lines.append(f"Сумма заказа: <code>{escape(total_rub)} р</code>")
    normalized_payment_method = _value_or_dash(payment_method)
    lines.append(f"Оплата: <code>{escape(normalized_payment_method)}</code>")
    if normalized_payment_method.lower() == "balance":
        lines.append(
            f"Balance after: <code>{escape(_value_or_dash(wallet_balance_after_rub))} р</code>"
        )
    if _value_or_dash(role) != "-":
        lines.append(f"Role: <code>{escape(_value_or_dash(role))}</code>")
    geo = _value_or_dash(reg_geo)
    loc = _value_or_dash(locale)
    if geo != "-" or loc != "-":
        lines.append(
            f"Reg geo: <code>{escape(geo)}</code> / Locale: <code>{escape(loc)}</code>"
        )
    if utm_params:
        lines.append("UTM params:")
        for key in sorted(utm_params.keys()):
            value = str(utm_params.get(key) or "").strip()
            if value:
                lines.append(f"- {escape(key)}: <code>{escape(value)}</code>")

    return "\n".join(lines)


def build_preorder_paid_notification_html(
    *,
    preorder_public_id: int,
    order_public_id: int,
    user_public_id: str | None,
    user_email: str | None,
    order_email: str | None,
    total_rub: str,
    payment_method: str | None,
    wallet_balance_after_rub: str | None,
    tg_auth: str | None,
    tg_handler: str | None,
    role: str | None,
    reg_geo: str | None,
    locale: str | None,
    utm_params: dict[str, str],
    items: list[dict],
    headline_html: str | None = None,
) -> str:
    """HTML for preorder paid Telegram message (same topic, single message → edit on fulfill)."""
    if headline_html is None:
        headline_html = f"<b>💤 Предзаказ на</b> <code>{escape(total_rub)} р</code>"
    normalized_user_email = _value_or_dash(user_email)
    normalized_order_email = _value_or_dash(order_email)
    if (
        normalized_user_email != "-"
        and normalized_order_email != "-"
        and normalized_user_email.lower() == normalized_order_email.lower()
    ):
        email_line = f"Email: <code>{escape(normalized_order_email)}</code>"
    else:
        email_line = (
            f"User email: <code>{escape(normalized_user_email)}</code>\n"
            f"Order email: <code>{escape(normalized_order_email)}</code>"
        )

    lines: list[str] = [
        headline_html,
        f"PreOrder ID: <code>{preorder_public_id}</code>",
        f"Order ID: <code>{order_public_id}</code>",
        f"User public id: <code>{escape(_value_or_dash(user_public_id))}</code>",
        "",
        email_line,
    ]

    if _value_or_dash(tg_auth) != "-":
        lines.append(f"TG AUTH: {escape(_tg_username_text(tg_auth))}")
    elif _value_or_dash(tg_handler) != "-":
        lines.append(f"TG Handler: {escape(_tg_username_text(tg_handler))}")

    lines.extend(["", "<b>Позиции:</b>"])
    for item in items:
        product_name = _value_or_dash(str(item.get("product_name", "") or ""))
        quantity = int(item.get("quantity") or 1)
        sku_line = _value_or_dash(str(item.get("sku_line", "") or ""))
        title = sku_line if sku_line != "-" else product_name
        lines.append(f"{escape(title)} x{quantity}")

    normalized_payment_method = _value_or_dash(payment_method)
    lines.append(f"Оплата: <code>{escape(normalized_payment_method)}</code>")
    if normalized_payment_method.lower() == "balance":
        lines.append(
            f"Balance after: <code>{escape(_value_or_dash(wallet_balance_after_rub))} р</code>"
        )
    if _value_or_dash(role) != "-":
        lines.append(f"Role: <code>{escape(_value_or_dash(role))}</code>")
    geo = _value_or_dash(reg_geo)
    loc = _value_or_dash(locale)
    if geo != "-" or loc != "-":
        lines.append(
            f"Reg geo: <code>{escape(geo)}</code> / Locale: <code>{escape(loc)}</code>"
        )
    if utm_params:
        lines.append("UTM params:")
        for key in sorted(utm_params.keys()):
            value = str(utm_params.get(key) or "").strip()
            if value:
                lines.append(f"- {escape(key)}: <code>{escape(value)}</code>")

    return "\n".join(lines)


COMPLETED_HEADLINE_HTML = "<b>COMPLETED ✅</b>"
