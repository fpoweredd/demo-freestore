from __future__ import annotations

import httpx
from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery
from loguru import logger

from bot.admin_handlers.forum import router as admin_router
from bot.admin_handlers.manual_order_html import COMPLETED_HEADLINE_HTML
from bot.config import BotSettings
from bot.manual_complete_token import (
    parse_manual_complete_callback,
    verify_manual_complete_callback_parts,
)

router = Router()


def _already_marked_completed(html: str) -> bool:
    s = (html or "").lstrip()
    return s.startswith(COMPLETED_HEADLINE_HTML) or s.startswith("COMPLETED ✅")


def register_manual_order_complete_handlers(settings: BotSettings) -> None:
    @router.callback_query(F.data.startswith("mf:"))
    async def complete_manual_order_cb(query: CallbackQuery) -> None:
        if settings.forum_chat_id == 0 or settings.topic_manual_orders == 0:
            await query.answer(
                "Manual orders topic is not configured.", show_alert=True
            )
            return

        msg = query.message
        if msg is None:
            await query.answer("No message.", show_alert=True)
            return

        chat = msg.chat
        if not chat or int(chat.id) != int(settings.forum_chat_id):
            await query.answer("Wrong chat.", show_alert=True)
            return

        thread_id = getattr(msg, "message_thread_id", None)
        if thread_id is None or int(thread_id) != int(settings.topic_manual_orders):
            await query.answer("Wrong topic.", show_alert=True)
            return

        uid = int(getattr(getattr(query, "from_user", None), "id", 0) or 0)
        if uid <= 0:
            await query.answer("No user.", show_alert=True)
            return
        try:
            member = await query.bot.get_chat_member(
                chat_id=settings.forum_chat_id, user_id=uid
            )
        except Exception:
            logger.exception("manual_complete_get_chat_member_failed")
            await query.answer("Cannot verify permissions.", show_alert=True)
            return
        status = str(getattr(member, "status", "") or "")
        if status not in {"administrator", "creator"}:
            await query.answer("Недостаточно прав.", show_alert=True)
            return

        parsed = parse_manual_complete_callback(query.data or "")
        if not parsed:
            await query.answer("Invalid button data.", show_alert=True)
            return
        order_public_id, sig = parsed
        secret = (settings.internal_api_key or "").strip()
        if not secret or not verify_manual_complete_callback_parts(
            order_public_id=order_public_id, sig=sig, secret=secret
        ):
            await query.answer("Invalid signature.", show_alert=True)
            return

        base = (settings.public_site_url or "").strip().rstrip("/")
        if not base:
            await query.answer(
                "PUBLIC_SITE_URL is not configured.",
                show_alert=True,
            )
            return

        url = f"{base}/internal/bot/manual-orders/complete/"
        # ngrok-free tier may close non-browser requests unless this header is set.
        headers = {
            "x-api-key": secret,
            "ngrok-skip-browser-warning": "1",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    url,
                    json={
                        "order_public_id": order_public_id,
                        "callback_token": sig,
                    },
                    headers=headers,
                )
        except Exception:
            logger.exception(
                "manual_complete_django_post_failed order_public_id={}",
                order_public_id,
            )
            await query.answer("Backend request failed.", show_alert=True)
            return

        if response.status_code == 401:
            await query.answer("API key mismatch (check env).", show_alert=True)
            return
        if response.status_code == 403:
            await query.answer("Token rejected.", show_alert=True)
            return
        if response.status_code == 404:
            await query.answer("Order not found.", show_alert=True)
            return
        if response.status_code == 409:
            await query.answer("Order is not in manual pending.", show_alert=True)
            return
        if response.status_code >= 400:
            await query.answer(f"Error {response.status_code}", show_alert=True)
            return

        try:
            body = response.json()
        except Exception:
            body = {}
        if not body.get("ok"):
            await query.answer("Unexpected backend response.", show_alert=True)
            return

        html_body = msg.html_text if msg.html_text else (msg.text or "")
        if _already_marked_completed(html_body):
            try:
                await msg.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await query.answer("Уже завершён.")
            return

        prefix = f"{COMPLETED_HEADLINE_HTML}\n\n"
        new_text = prefix + html_body
        if len(new_text) > 4096:
            new_text = new_text[:4093] + "..."

        try:
            await msg.edit_text(
                new_text,
                parse_mode=ParseMode.HTML,
                reply_markup=None,
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception(
                "manual_complete_edit_message_failed order_public_id={}",
                order_public_id,
            )
            await query.answer(
                "Order completed but failed to edit the message.",
                show_alert=True,
            )
            return

        await query.answer("Готово")


def include_manual_complete_router() -> None:
    """Attach callback router to the same admin router bundle used in main."""
    admin_router.include_router(router)
