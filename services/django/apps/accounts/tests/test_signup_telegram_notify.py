from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.accounts.services import register_user

User = get_user_model()


@override_settings(
    BOT_INTERNAL_SIGNUP_API_URL="http://bot.test/internal/signups/notify",
    BOT_INTERNAL_API_KEY="test-key",
)
class SignupTelegramNotifyTests(TestCase):
    @patch("apps.accounts.telegram_notify.post_signup_notify", return_value=True)
    def test_register_user_sends_signup_notify_once(self, mock_post):
        user, created = register_user(
            email="newuser@example.com",
            password="strongpass1",
            registration_ip="203.0.113.10",
        )
        self.assertTrue(created)
        mock_post.assert_called_once()
        payload = mock_post.call_args[0][0]
        self.assertEqual(payload["registration_method"], "email")
        self.assertEqual(payload["user_email"], user.email)
        self.assertTrue(str(payload["user_public_id"]).isdigit())

        mock_post.reset_mock()
        user2, created2 = register_user(
            email="newuser@example.com",
            password="anotherpass1",
        )
        self.assertFalse(created2)
        self.assertEqual(user2.pk, user.pk)
        mock_post.assert_not_called()
