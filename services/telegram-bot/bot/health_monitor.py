from __future__ import annotations

import asyncio
from html import escape

import httpx
from aiogram import Bot
from loguru import logger

from bot.config import BotSettings


async def _send_error_report(bot: Bot, settings: BotSettings, details: str) -> None:
    if settings.forum_chat_id == 0 or settings.topic_errors == 0:
        return
    await bot.send_message(
        chat_id=settings.forum_chat_id,
        message_thread_id=settings.topic_errors,
        text=(
            "<b>Health check failed</b>\n"
            f"base_url: {settings.public_site_url or '-'}\n"
            f"{details}"
        ),
        disable_web_page_preview=True,
    )


async def check_django_health_once(bot: Bot, settings: BotSettings) -> None:
    base_url = settings.public_site_url
    if not base_url:
        return

    timeout = httpx.Timeout(settings.healthcheck_timeout_seconds)
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for endpoint in ("/healthz", "/readyz"):
            url = f"{base_url}{endpoint}"
            try:
                response = await client.get(url)
                if response.status_code != 200:
                    errors.append(
                        f"<code>{endpoint}</code>: status=<code>{response.status_code}</code>"
                    )
            except Exception as exc:
                errors.append(
                    f"<code>{endpoint}</code>: error=<code>{escape(type(exc).__name__ + ': ' + str(exc))}</code>"
                )

    if errors:
        details = "\n".join(f"- {line}" for line in errors)
        try:
            await _send_error_report(bot, settings, details)
        except Exception:
            logger.exception("failed_to_send_health_error_report")


async def run_periodic_health_monitor(bot: Bot, settings: BotSettings) -> None:
    if settings.healthcheck_initial_delay_seconds > 0:
        await asyncio.sleep(settings.healthcheck_initial_delay_seconds)
    await check_django_health_once(bot, settings)
    while True:
        await asyncio.sleep(settings.healthcheck_interval_seconds)
        await check_django_health_once(bot, settings)
