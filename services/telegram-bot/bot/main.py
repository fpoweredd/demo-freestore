from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from bot.admin_handlers.forum import register_admin_handlers
from bot.admin_handlers.forum import router as admin_router
from bot.admin_handlers.manual_order_complete import (
    include_manual_complete_router,
    register_manual_order_complete_handlers,
)
from bot.api import bind_runtime, run_api_server
from bot.config import get_settings
from bot.db.db import init_models
from bot.handlers.start import register_start_handlers
from bot.handlers.start import router as start_router
from bot.health_monitor import run_periodic_health_monitor
from bot.logging_setup import configure_logging


async def run() -> None:
    configure_logging()
    settings = get_settings()
    if not settings.token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    await init_models()

    bot = Bot(
        token=settings.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    bind_runtime(bot=bot, settings=settings)
    dp = Dispatcher()
    register_start_handlers(settings)
    register_admin_handlers(settings)
    register_manual_order_complete_handlers(settings)
    include_manual_complete_router()
    dp.include_router(start_router)
    dp.include_router(admin_router)

    logger.info("telegram_bot_starting forum_chat_id={}", settings.forum_chat_id)
    if settings.forum_chat_id != 0 and settings.topic_logs != 0:
        try:
            await bot.send_message(
                chat_id=settings.forum_chat_id,
                message_thread_id=settings.topic_logs,
                text="✅ Bot started",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("failed_to_send_bot_start_log_message")
    health_monitor_task = asyncio.create_task(run_periodic_health_monitor(bot, settings))
    api_server_task = asyncio.create_task(run_api_server(settings))
    try:
        await dp.start_polling(bot)
    finally:
        health_monitor_task.cancel()
        api_server_task.cancel()
        await asyncio.gather(
            health_monitor_task,
            api_server_task,
            return_exceptions=True,
        )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
