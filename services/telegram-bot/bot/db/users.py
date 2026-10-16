from __future__ import annotations

from datetime import datetime

from aiogram.types import User as TelegramUser
from sqlalchemy import select

from bot.db.db import AsyncSessionLocal
from bot.db.models import BotUser


async def upsert_bot_user_from_start(
    *,
    user: TelegramUser,
    start_param: str | None,
) -> tuple[BotUser, bool]:
    now = datetime.utcnow()
    normalized_start_param = (start_param or "").strip() or None

    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(BotUser).where(BotUser.telegram_id == user.id))
        ).scalar_one_or_none()

        if existing is None:
            entity = BotUser(
                telegram_id=user.id,
                username=(user.username or "").strip() or None,
                first_name=(user.first_name or "").strip() or None,
                last_name=(user.last_name or "").strip() or None,
                start_param=normalized_start_param,
                is_active=True,
                activation_date=now,
                last_interaction_at=now,
            )
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
            return entity, True

        existing.username = (user.username or "").strip() or existing.username
        existing.first_name = (user.first_name or "").strip() or existing.first_name
        existing.last_name = (user.last_name or "").strip() or existing.last_name
        if normalized_start_param:
            existing.start_param = normalized_start_param
        existing.is_active = True
        existing.last_interaction_at = now
        await session.commit()
        await session.refresh(existing)
        return existing, False
