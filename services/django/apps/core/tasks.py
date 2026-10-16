from __future__ import annotations

from celery import shared_task
from loguru import logger

from .session_cleanup import cleanup_expired_sessions


@shared_task
def cleanup_expired_sessions_task() -> int:
    deleted = int(cleanup_expired_sessions())
    logger.info("cleanup_expired_sessions_task deleted={}", deleted)
    return deleted
