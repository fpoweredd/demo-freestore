from django.urls import path

from .views import (
    AccountMeAPIView,
    LoginAPIView,
    LogoutAPIView,
    PasswordResetConfirmAPIView,
    PasswordResetRequestAPIView,
    RegisterAPIView,
)

app_name = "accounts-api"

urlpatterns = [
    path("auth/register/", RegisterAPIView.as_view(), name="auth-register"),
    path("auth/login/", LoginAPIView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutAPIView.as_view(), name="auth-logout"),
    path("auth/password-reset/", PasswordResetRequestAPIView.as_view(), name="auth-password-reset"),
    path("auth/password-reset/confirm/", PasswordResetConfirmAPIView.as_view(), name="auth-password-reset-confirm"),
    path("accounts/me/", AccountMeAPIView.as_view(), name="accounts-me"),
]
