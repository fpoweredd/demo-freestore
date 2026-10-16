from __future__ import annotations

from django.contrib.sessions.models import Session
from django.utils import timezone
from loguru import logger


def cleanup_expired_sessions() -> int:
    """
    Delete rows from django_session where expire_date < now.
    Same logic as `manage.py clearsessions`.
    """
    qs = Session.objects.filter(expire_date__lt=timezone.now())
    deleted, _details = qs.delete()
    count = int(deleted or 0)
    logger.info("cleanup_expired_sessions deleted={}", count)
    return count
