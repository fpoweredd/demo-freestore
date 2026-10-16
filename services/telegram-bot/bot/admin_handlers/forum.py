from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import BotSettings

router = Router()


async def _is_forum_admin_message(message: Message, settings: BotSettings) -> bool:
    """
    Allow these commands only inside the configured forum chat
    and only for chat admins/owner (no ID allowlists, no personal DMs).
    """
    if settings.forum_chat_id == 0:
        return False
    if not message.chat or int(message.chat.id) != int(settings.forum_chat_id):
        return False
    user_id = int(getattr(getattr(message, "from_user", None), "id", 0) or 0)
    if user_id <= 0:
        return False
    try:
        member = await message.bot.get_chat_member(
            chat_id=settings.forum_chat_id, user_id=user_id
        )
    except Exception:
        return False
    status = str(getattr(member, "status", "") or "")
    return status in {"administrator", "creator"}


def _topics_overview(settings: BotSettings) -> str:
    rows: list[str] = []
    mapping = [
        ("General", settings.topic_general),
        ("Bot /start", settings.topic_bot_start),
        ("Manual Orders", settings.topic_manual_orders),
        ("Preorders", settings.topic_preorders),
        ("Errors", settings.topic_errors),
        ("Logs", settings.topic_logs),
        ("Sign Ups", settings.topic_signups),
        ("Top-Ups", settings.topic_topups),
        ("Orders", settings.topic_orders),
    ]
    for title, topic_id in mapping:
        value = topic_id if topic_id > 0 else "not configured"
        rows.append(f"- {title}: {value}")
    return "\n".join(rows)


def _configured_topics(settings: BotSettings) -> list[tuple[str, int]]:
    mapping = [
        ("General", settings.topic_general),
        ("Bot /start", settings.topic_bot_start),
        ("Manual Orders", settings.topic_manual_orders),
        ("Preorders", settings.topic_preorders),
        ("Errors", settings.topic_errors),
        ("Logs", settings.topic_logs),
        ("Sign Ups", settings.topic_signups),
        ("Top-Ups", settings.topic_topups),
        ("Orders", settings.topic_orders),
    ]
    return [(title, topic_id) for title, topic_id in mapping if topic_id > 0]


def register_admin_handlers(settings: BotSettings) -> None:
    @router.message(Command("topics"))
    async def topics_cmd(message: Message) -> None:
        if not await _is_forum_admin_message(message, settings):
            return
        await message.answer("Configured forum topics:\n" + _topics_overview(settings))

    @router.message(Command("test_topics"))
    async def test_topics_cmd(message: Message) -> None:
        if not await _is_forum_admin_message(message, settings):
            return
        topics = _configured_topics(settings)
        if settings.forum_chat_id == 0:
            await message.answer("TG_FORUM_CHAT_ID is not configured.")
            return
        if not topics:
            await message.answer("No configured topics found.")
            return

        sent_count = 0
        failed: list[str] = []
        for title, topic_id in topics:
            try:
                await message.bot.send_message(
                    chat_id=settings.forum_chat_id,
                    message_thread_id=topic_id,
                    text=(
                        "Test notification from Freestore bot.\n"
                        f"Topic: {title}\n"
                        f"Thread ID: {topic_id}"
                    ),
                )
                sent_count += 1
            except Exception as exc:
                failed.append(f"{title} ({topic_id}): {exc}")

        result_lines = [f"Test dispatch complete. Sent: {sent_count}/{len(topics)}"]
        if failed:
            result_lines.append("Failed:")
            result_lines.extend(f"- {item}" for item in failed)
        await message.answer("\n".join(result_lines))
