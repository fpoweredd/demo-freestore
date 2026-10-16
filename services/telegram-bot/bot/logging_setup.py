from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger


def configure_logging() -> None:
    logs_dir = Path("/app/logs/telegram-bot")
    if not logs_dir.exists():
        logs_dir = Path(__file__).resolve().parents[3] / "logs" / "telegram-bot"
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stdout,
        level=os.getenv("BOT_LOG_LEVEL", "INFO"),
        enqueue=True,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>",
    )
    logger.add(
        logs_dir / "app_{time:YYYY-MM-DD}.log",
        level="INFO",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        enqueue=True,
        encoding="utf-8",
    )
    logger.add(
        logs_dir / "error_{time:YYYY-MM-DD}.log",
        level="ERROR",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        enqueue=True,
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
    )
