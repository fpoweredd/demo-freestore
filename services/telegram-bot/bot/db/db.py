from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import get_settings
from bot.db.models import Base

settings = get_settings()

if settings.database_url.startswith("sqlite+"):
    sqlite_path = settings.database_url.replace("sqlite+aiosqlite:///", "", 1)
    if sqlite_path:
        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(settings.database_url, future=True, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_models() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
