from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import PasswordResetRequest

User = get_user_model()


class AccountsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_and_login(self):
        resp = self.client.post(reverse("accounts-api:auth-register"), {"email": "u1@example.com", "password": "strongpass1"}, format="json")
        self.assertEqual(resp.status_code, 201)

        resp_login = self.client.post(reverse("accounts-api:auth-login"), {"email": "u1@example.com", "password": "strongpass1"}, format="json")
        self.assertEqual(resp_login.status_code, 200)

    def test_password_reset_issue_and_confirm(self):
        user = User.objects.create_user(username="u2", email="u2@example.com", password="strongpass1")
        resp = self.client.post(reverse("accounts-api:auth-password-reset"), {"email": user.email}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("token", resp.data)
        row = PasswordResetRequest.objects.filter(user=user).order_by("-id").first()
        self.assertIsNotNone(row)
        token = row.token

        resp_confirm = self.client.post(
            reverse("accounts-api:auth-password-reset-confirm"),
            {"token": token, "password": "newstrongpass2"},
            format="json",
        )
        self.assertEqual(resp_confirm.status_code, 200)

    def test_password_reset_api_does_not_leak_token_for_unknown_email(self):
        resp = self.client.post(
            reverse("accounts-api:auth-password-reset"),
            {"email": "nobody-here@example.com"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("token", resp.data)

    def test_oauth_complete_endpoint_removed(self):
        from django.urls import NoReverseMatch

        with self.assertRaises(NoReverseMatch):
            reverse("accounts-api:auth-oauth-complete")

    def test_me_patch_updates_telegram_handle(self):
        user = User.objects.create_user(username="u4", email="u4@example.com", password="strongpass1")
        self.client.force_authenticate(user=user)
        resp = self.client.patch(reverse("accounts-api:accounts-me"), {"telegram_handle": "@myhandle"}, format="json")
        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.account_profile.telegram_handle, "@myhandle")
