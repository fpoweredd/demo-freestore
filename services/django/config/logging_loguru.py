from __future__ import annotations

import logging
import sys
from pathlib import Path

from loguru import logger


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except Exception:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def configure_loguru(root_dir: Path, debug: bool) -> None:
    logs_dir = root_dir / "logs" / "django"
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stdout,
        level="DEBUG" if debug else "INFO",
        colorize=True,
        enqueue=True,
        backtrace=debug,
        diagnose=debug,
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
        diagnose=debug,
    )

    intercept_handler = InterceptHandler()
    logging.root.handlers = [intercept_handler]
    logging.root.setLevel(logging.NOTSET)

    for name in logging.root.manager.loggerDict.keys():
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    # Reduce noisy debug output in dev terminal.
    # Keeps useful app logs while hiding SQL/template resolver spam.
    noisy_loggers = {
        "django.db.backends": logging.WARNING,
        "django.template": logging.WARNING,
        "django.utils.autoreload": logging.INFO,
    }
    for logger_name, level in noisy_loggers.items():
        logging.getLogger(logger_name).setLevel(level)
