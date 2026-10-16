from __future__ import annotations

from html import escape
from time import monotonic

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger

from bot.config import BotSettings
from bot.db.users import upsert_bot_user_from_start
from bot.user_msgs import MESSAGES

router = Router()
_START_COOLDOWN_UNTIL: dict[int, float] = {}


def _render(text: str, **values: str) -> str:
    rendered = text
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def register_start_handlers(settings: BotSettings) -> None:
    @router.message(Command("start"))
    async def start_cmd(message: Message) -> None:
        if message.from_user is not None:
            now = monotonic()
            cooldown_until = _START_COOLDOWN_UNTIL.get(message.from_user.id, 0.0)
            if cooldown_until > now:
                return
            _START_COOLDOWN_UNTIL[message.from_user.id] = now + float(
                settings.start_cooldown_seconds
            )

        raw_text = (message.text or "").strip()
        start_param = None
        if " " in raw_text:
            start_param = raw_text.split(" ", 1)[1].strip() or None

        is_new_user = False
        db_user = None
        if message.from_user is not None:
            try:
                db_user, is_new_user = await upsert_bot_user_from_start(
                    user=message.from_user,
                    start_param=start_param,
                )
            except Exception:
                logger.exception("failed_to_upsert_bot_user_on_start")

        if (
            message.from_user is not None
            and is_new_user
            and settings.forum_chat_id != 0
            and settings.topic_bot_start != 0
        ):
            try:
                username = (
                    f"@{message.from_user.username}"
                    if message.from_user.username
                    else "-"
                )
                first_name = (message.from_user.first_name or "").strip() or "-"
                last_name = (message.from_user.last_name or "").strip() or "-"
                title = "👤 Новый пользователь"
                language_code = (message.from_user.language_code or "").strip() or "-"
                lines = [
                    title,
                    f"ID: <code>{message.from_user.id}</code>",
                    f"Username: <code>{escape(username)}</code>",
                    f"Имя: <code>{escape(first_name)}</code>",
                    f"Фамилия: <code>{escape(last_name)}</code>",
                    f"Language code: <code>{escape(language_code)}</code>",
                    # "Locale (bot): <code>ru</code>",
                ]
                if start_param:
                    lines.append(f"Start params: <code>{escape(start_param)}</code>")
                if db_user is not None:
                    lines.append(f"DB user ID: <code>{db_user.id}</code>")

                await message.bot.send_message(
                    chat_id=settings.forum_chat_id,
                    message_thread_id=settings.topic_bot_start,
                    text="\n".join(lines),
                    disable_web_page_preview=True,
                )
            except Exception:
                logger.exception("failed_to_send_start_activation_notification")

        start_url = settings.start_button_url
        start_button = InlineKeyboardButton(
            text=MESSAGES["start_button"],
            url=start_url,
            style="primary",
            icon_custom_emoji_id="5339513551524481000",
        )

        start_button_markup = InlineKeyboardMarkup(inline_keyboard=[[start_button]])
        await message.answer(
            _render(MESSAGES["start"], start_button_url=start_url),
            disable_web_page_preview=True,
            reply_markup=start_button_markup,
        )

