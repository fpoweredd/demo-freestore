from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("accounts/login/", views.login_view, name="login"),
    path("accounts/register/", views.register_view, name="register"),
    path("accounts/logout/", views.logout_view, name="logout"),
    path("accounts/profile/", views.account_profile_view, name="profile"),
    path("accounts/orders/", views.account_orders_view, name="orders"),
    path("accounts/balance/", views.account_balance_view, name="balance"),
    path(
        "accounts/balance/topup-result/",
        views.account_balance_topup_result_view,
        name="balance_topup_result",
    ),
    path(
        "accounts/balance/start/",
        views.account_balance_topup_start_view,
        name="balance_topup_start",
    ),
    path(
        "accounts/set-email-once/",
        views.account_set_email_once_view,
        name="set-email-once",
    ),
    path(
        "accounts/password-reset/",
        views.password_reset_request_view,
        name="password-reset-request",
    ),
    path(
        "accounts/password-reset/confirm/",
        views.password_reset_confirm_view,
        name="password-reset-confirm",
    ),
    path("accounts/oauth-step-up/", views.oauth_step_up_view, name="oauth-step-up"),
    path(
        "accounts/oauth/google/start/",
        views.google_oauth_start_view,
        name="oauth-google-start",
    ),
    path(
        "accounts/oauth/google/callback/",
        views.google_oauth_callback_view,
        name="oauth-google-callback",
    ),
    path(
        "accounts/oauth/telegram/start/",
        views.telegram_oidc_start_view,
        name="oauth-telegram-start",
    ),
    path(
        "accounts/oauth/telegram/callback/",
        views.telegram_oidc_callback_view,
        name="telegram-oidc-callback",
    ),
    path(
        "accounts/oauth/telegram/webapp/complete/",
        views.telegram_webapp_auto_login_view,
        name="oauth-telegram-webapp-complete",
    ),
    path("accounts/modal/login/", views.auth_modal_login, name="auth-modal-login"),
]
