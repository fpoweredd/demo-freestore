from __future__ import annotations

from html import escape

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

from bot.admin_handlers.manual_order_html import (
    COMPLETED_HEADLINE_HTML,
    build_manual_order_notification_html,
    build_preorder_paid_notification_html,
)
from bot.config import BotSettings
from bot.manual_complete_token import manual_complete_callback_data


def _value_or_dash(value: str | None) -> str:
    return (value or "").strip() or "-"


def _tg_username_text(value: str | None) -> str:
    normalized = _value_or_dash(value)
    if normalized == "-":
        return normalized
    return normalized if normalized.startswith("@") else f"@{normalized}"


def _preorder_body_already_completed(html: str) -> bool:
    s = (html or "").lstrip()
    return s.startswith(COMPLETED_HEADLINE_HTML)


async def send_order_notification_to_topic(
    *,
    bot: Bot,
    settings: BotSettings,
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
) -> None:
    if settings.forum_chat_id == 0 or settings.topic_orders == 0:
        return

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
        f"<b>🧾 Заказ на</b> <code>{escape(total_rub)} р</code>",
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

        sku_params = item.get("sku_params") or {}
        if isinstance(sku_params, dict) and sku_params:
            for key in sorted(sku_params.keys()):
                value = str(sku_params.get(key) or "").strip()
                if value:
                    lines.append(f"- {escape(str(key))}: <code>{escape(value)}</code>")
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

    await bot.send_message(
        chat_id=settings.forum_chat_id,
        message_thread_id=settings.topic_orders,
        text="\n".join(lines),
        disable_web_page_preview=True,
    )


async def send_manual_order_notification_to_topic(
    *,
    bot: Bot,
    settings: BotSettings,
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
) -> tuple[int, int] | None:
    """
    Sends a message to the configured Manual Orders topic.
    Returns (chat_id, message_id) on success.
    """
    if settings.forum_chat_id == 0 or settings.topic_manual_orders == 0:
        return None

    text = build_manual_order_notification_html(
        order_public_id=order_public_id,
        user_public_id=user_public_id,
        user_email=user_email,
        order_email=order_email,
        guest_email=guest_email,
        total_rub=total_rub,
        payment_method=payment_method,
        wallet_balance_after_rub=wallet_balance_after_rub,
        tg_auth=tg_auth,
        tg_handler=tg_handler,
        role=role,
        reg_geo=reg_geo,
        locale=locale,
        utm_params=utm_params,
        items=items,
    )
    keyboard = None
    secret = (settings.internal_api_key or "").strip()
    if secret:
        try:
            cb = manual_complete_callback_data(
                order_public_id=order_public_id, secret=secret
            )
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Завершить", callback_data=cb)]
                ]
            )
        except ValueError as exc:
            logger.warning(
                "manual_order_inline_keyboard_disabled order_public_id={} detail={}",
                order_public_id,
                exc,
            )
            keyboard = None
        except Exception:
            logger.exception(
                "manual_order_inline_keyboard_failed order_public_id={}",
                order_public_id,
            )
            keyboard = None
    msg = await bot.send_message(
        chat_id=settings.forum_chat_id,
        message_thread_id=settings.topic_manual_orders,
        text=text,
        disable_web_page_preview=True,
        reply_markup=keyboard,
    )
    return (int(msg.chat.id), int(msg.message_id))


async def send_preorder_paid_notification_to_topic(
    *,
    bot: Bot,
    settings: BotSettings,
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
    admin_upload_url: str | None,
    items: list[dict],
) -> tuple[int, int, str] | None:
    """
    Sends preorder paid HTML to the preorders topic.
    Returns (chat_id, message_id, text) for later edit on fulfill.
    """
    if settings.forum_chat_id == 0 or settings.topic_preorders == 0:
        return None

    text = build_preorder_paid_notification_html(
        preorder_public_id=preorder_public_id,
        order_public_id=order_public_id,
        user_public_id=user_public_id,
        user_email=user_email,
        order_email=order_email,
        total_rub=total_rub,
        payment_method=payment_method,
        wallet_balance_after_rub=wallet_balance_after_rub,
        tg_auth=tg_auth,
        tg_handler=tg_handler,
        role=role,
        reg_geo=reg_geo,
        locale=locale,
        utm_params=utm_params,
        items=items,
    )

    keyboard = None
    direct_upload_url = str(admin_upload_url or "").strip()
    if direct_upload_url:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Загрузить товар",
                        url=direct_upload_url,
                    )
                ]
            ]
        )

    msg = await bot.send_message(
        chat_id=settings.forum_chat_id,
        message_thread_id=settings.topic_preorders,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=keyboard,
    )
    return (int(msg.chat.id), int(msg.message_id), text)


async def edit_preorder_notification_to_completed(
    *,
    bot: Bot,
    chat_id: int,
    message_id: int,
    previous_text: str,
) -> None:
    if _preorder_body_already_completed(previous_text):
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=message_id, reply_markup=None
            )
        except Exception:
            logger.exception(
                "preorder_completed_strip_keyboard_failed chat_id={} message_id={}",
                chat_id,
                message_id,
            )
        return
    new_text = f"{COMPLETED_HEADLINE_HTML}\n\n{previous_text}"
    if len(new_text) > 4096:
        new_text = new_text[:4093] + "..."
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=new_text,
        parse_mode=ParseMode.HTML,
        reply_markup=None,
        disable_web_page_preview=True,
    )


async def send_preorder_fulfilled_notification_to_topic(
    *,
    bot: Bot,
    settings: BotSettings,
    preorder_public_id: int,
    order_public_id: int,
    user_public_id: str | None,
    user_email: str | None,
    order_email: str | None,
    tg_auth: str | None,
    tg_handler: str | None,
    items: list[dict],
) -> None:
    if settings.forum_chat_id == 0 or settings.topic_preorders == 0:
        return

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
        "<b>✅ Предзаказ исполнен</b>",
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

    await bot.send_message(
        chat_id=settings.forum_chat_id,
        message_thread_id=settings.topic_preorders,
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


_SIGNUP_METHOD_LABELS = {
    "email": "Email (usual)",
    "google": "Google",
    "telegram": "Telegram",
}


async def send_signup_notification_to_topic(
    *,
    bot: Bot,
    settings: BotSettings,
    user_public_id: str | None,
    user_email: str | None,
    registration_method: str,
    reg_geo: str | None,
    locale: str | None,
    registration_ip: str | None,
    utm_params: dict[str, str],
    tg_auth: str | None,
    tg_handler: str | None,
) -> None:
    if settings.forum_chat_id == 0 or settings.topic_signups == 0:
        return

    method_key = (registration_method or "").strip().lower()
    method_label = _SIGNUP_METHOD_LABELS.get(method_key, registration_method or "-")

    lines: list[str] = [
        f"<b>👤 Регистрация через <code>{escape(method_label)}</code></b>",
        f"Email: <code>{escape(_value_or_dash(user_email))}</code>",
        f"User public id: <code>{escape(_value_or_dash(user_public_id))}</code>",
    ]

    if _value_or_dash(tg_auth) != "-":
        lines.append(f"TG AUTH: {escape(_tg_username_text(tg_auth))}")
    elif _value_or_dash(tg_handler) != "-":
        lines.append(f"TG Handler: {escape(_tg_username_text(tg_handler))}")

    geo = _value_or_dash(reg_geo)
    loc = _value_or_dash(locale)
    if geo != "-" or loc != "-":
        lines.append(
            f"Reg geo: <code>{escape(geo)}</code> / Locale: <code>{escape(loc)}</code>"
        )
    if _value_or_dash(registration_ip) != "-":
        lines.append(f"Reg IP: <code>{escape(_value_or_dash(registration_ip))}</code>")

    if utm_params:
        lines.append("UTM params:")
        for key in sorted(utm_params.keys()):
            value = str(utm_params.get(key) or "").strip()
            if value:
                lines.append(f"- {escape(key)}: <code>{escape(value)}</code>")

    await bot.send_message(
        chat_id=settings.forum_chat_id,
        message_thread_id=settings.topic_signups,
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def send_topup_notification_to_topic(
    *,
    bot: Bot,
    settings: BotSettings,
    topup_public_id: int,
    payment_id: str,
    provider_id: str,
    amount_rub: str,
    currency: str,
    status: str,
    success: bool,
    reason: str | None,
    user_public_id: str | None,
    user_email: str | None,
) -> None:
    target_topic = settings.topic_topups if success else settings.topic_logs
    if settings.forum_chat_id == 0 or target_topic == 0:
        return
    title = (
        "💳 Успешное пополнение баланса"
        if success
        else "❌ Неуспешное пополнение баланса"
    )
    lines = [
        f"<b>{title}</b>",
        f"TopUp ID: <code>{topup_public_id}</code>",
        f"Payment ID: <code>{escape(_value_or_dash(payment_id))}</code>",
        f"User public id: <code>{escape(_value_or_dash(user_public_id))}</code>",
        f"Email: <code>{escape(_value_or_dash(user_email))}</code>",
        f"Платежка: <code>{escape(_value_or_dash(provider_id))}</code>",
        f"Сумма пополнения: <code>{escape(_value_or_dash(amount_rub))} {escape(_value_or_dash(currency))}</code>",
        f"Статус: <code>{escape(_value_or_dash(status))}</code>",
    ]
    if not success and _value_or_dash(reason) != "-":
        lines.append(f"Причина: <code>{escape(_value_or_dash(reason))}</code>")
    await bot.send_message(
        chat_id=settings.forum_chat_id,
        message_thread_id=target_topic,
        text="\n".join(lines),
        disable_web_page_preview=True,
    )


async def send_payment_error_to_logs_topic(
    *,
    bot: Bot,
    settings: BotSettings,
    provider_id: str,
    error_code: str,
    error_message: str,
    context: dict[str, str] | None = None,
) -> None:
    if settings.forum_chat_id == 0 or settings.topic_logs == 0:
        return
    lines = [
        "<b>🚨 Payment error</b>",
        f"Provider: <code>{escape(_value_or_dash(provider_id))}</code>",
        f"Code: <code>{escape(_value_or_dash(error_code))}</code>",
        f"Message: <code>{escape(_value_or_dash(error_message))}</code>",
    ]
    if context:
        lines.append("Context:")
        for key in sorted(context.keys()):
            value = str(context.get(key) or "").strip()
            if value:
                lines.append(
                    f"- <code>{escape(key)}</code>: <code>{escape(value)}</code>"
                )
    await bot.send_message(
        chat_id=settings.forum_chat_id,
        message_thread_id=settings.topic_logs,
        text="\n".join(lines),
        disable_web_page_preview=True,
    )
