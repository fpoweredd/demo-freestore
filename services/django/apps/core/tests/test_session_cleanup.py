from datetime import timedelta

from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils import timezone

from apps.core.session_cleanup import cleanup_expired_sessions


class SessionCleanupTests(TestCase):
    def test_deletes_only_expired_sessions(self):
        expired_key = "expired-session-key-01"
        active_key = "active-session-key-01"
        Session.objects.create(
            session_key=expired_key,
            session_data="e30:1abc",
            expire_date=timezone.now() - timedelta(days=1),
        )
        Session.objects.create(
            session_key=active_key,
            session_data="e30:1def",
            expire_date=timezone.now() + timedelta(days=7),
        )

        deleted = cleanup_expired_sessions()
        self.assertEqual(deleted, 1)
        self.assertFalse(Session.objects.filter(session_key=expired_key).exists())
        self.assertTrue(Session.objects.filter(session_key=active_key).exists())
