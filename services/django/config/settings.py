import os
from pathlib import Path

from decouple import Config, Csv, RepositoryEnv

from config.logging_loguru import configure_loguru

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent.parent
ENV_PATH = ROOT_DIR / ".env"
env_config = Config(RepositoryEnv(str(ENV_PATH))) if ENV_PATH.exists() else None


def get_env(name: str, default=None, cast=str):
    raw_from_os = os.getenv(name)
    if raw_from_os is not None:
        if cast in (None, str):
            return raw_from_os
        if cast is bool:
            return str(raw_from_os).strip().lower() in {"1", "true", "yes", "on"}
        try:
            return cast(raw_from_os) if callable(cast) else raw_from_os
        except Exception:
            return raw_from_os
    if env_config:
        return env_config(name, default=default, cast=cast)
    if default is None:
        return None
    return cast(default) if callable(cast) else default


SECRET_KEY = get_env("SECRET_KEY", default="django-insecure-change-me")
DEBUG = get_env("DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = get_env("ALLOWED_HOSTS", default="127.0.0.1,localhost", cast=Csv())
CSRF_TRUSTED_ORIGINS = get_env("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

USE_X_FORWARDED_HOST = get_env("USE_X_FORWARDED_HOST", default=False, cast=bool)
if get_env("TRUST_X_FORWARDED_PROTO", default=False, cast=bool):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HTTPS in browser + HTTP to Gunicorn: set secure cookies when terminating TLS upstream.
if not DEBUG and get_env("TRUST_X_FORWARDED_PROTO", default=False, cast=bool):
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# OAuth / Integrations
GOOGLE_CLIENT_ID = get_env("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = get_env("GOOGLE_CLIENT_SECRET", default="")
TELEGRAM_BOT_TOKEN = get_env("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_BOT_USERNAME = get_env("TELEGRAM_BOT_USERNAME", default="")
# Origins allowed for POST /accounts/telegram-webapp-login/ (Telegram Mini App).
TELEGRAM_WEBAPP_ALLOWED_ORIGINS = get_env(
    "TELEGRAM_WEBAPP_ALLOWED_ORIGINS",
    default="https://web.telegram.org,https://telegram.org,https://t.me",
    cast=Csv(),
)
TELEGRAM_OIDC_CLIENT_ID = get_env("TELEGRAM_OIDC_CLIENT_ID", default="")
TELEGRAM_OIDC_CLIENT_SECRET = get_env("TELEGRAM_OIDC_CLIENT_SECRET", default="")
BOT_INTERNAL_API_URL = get_env(
    "BOT_INTERNAL_API_BASE_URL", default="http://127.0.0.1:8091"
).rstrip("/")
BOT_INTERNAL_API_KEY = get_env("BOT_INTERNAL_API_KEY", default="")
BOT_INTERNAL_ORDER_API_URL = BOT_INTERNAL_API_URL + "/internal/orders/notify"
BOT_INTERNAL_MANUAL_ORDER_API_URL = (
    BOT_INTERNAL_API_URL + "/internal/manual-orders/notify"
)
BOT_INTERNAL_PREORDER_API_URL = BOT_INTERNAL_API_URL + "/internal/preorders/notify-paid"
BOT_INTERNAL_PREORDER_FULFILLED_API_URL = (
    BOT_INTERNAL_API_URL + "/internal/preorders/notify-fulfilled"
)
BOT_INTERNAL_TOPUP_API_URL = BOT_INTERNAL_API_URL + "/internal/topups/notify"
BOT_INTERNAL_SIGNUP_API_URL = BOT_INTERNAL_API_URL + "/internal/signups/notify"
BOT_INTERNAL_PAYMENTS_ERROR_API_URL = BOT_INTERNAL_API_URL + "/internal/payments/errors"

# Cloudflare Turnstile
TURNSTILE_SITE_KEY = get_env("TURNSTILE_SITE_KEY", default="")
TURNSTILE_SECRET_KEY = get_env("TURNSTILE_SECRET_KEY", default="")
TURNSTILE_LOGIN_FAIL_THRESHOLD = get_env(
    "TURNSTILE_LOGIN_FAIL_THRESHOLD", default=3, cast=int
)
PASSWORD_RESET_REQUEST_LIMIT = get_env(
    "PASSWORD_RESET_REQUEST_LIMIT", default=5, cast=int
)

# SMTP / email
EMAIL_BACKEND = get_env(
    "EMAIL_BACKEND",
    default=(
        "django.core.mail.backends.console.EmailBackend"
        if bool(DEBUG)
        else "django.core.mail.backends.smtp.EmailBackend"
    ),
)
# If unset, reuse docker-mailserver FQDN from credentials/.env (same as compose MAILSERVER_OVERRIDE_HOSTNAME).
_mailserver_fqdn = (get_env("MAILSERVER_OVERRIDE_HOSTNAME", default="") or "").strip()
EMAIL_HOST = (get_env("EMAIL_HOST", default="") or "").strip() or _mailserver_fqdn
EMAIL_PORT = get_env("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = get_env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = get_env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = get_env("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_USE_SSL = get_env("EMAIL_USE_SSL", default=False, cast=bool)
DEFAULT_FROM_EMAIL = get_env("DEFAULT_FROM_EMAIL", default="no-reply@example.com")
SERVER_EMAIL = get_env("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)

# Celery
CELERY_BROKER_URL = get_env("CELERY_BROKER_URL", default="redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = get_env("CELERY_RESULT_BACKEND", default="")
CELERY_TASK_ALWAYS_EAGER = get_env("CELERY_TASK_ALWAYS_EAGER", default=False, cast=bool)
CELERY_TASK_EAGER_PROPAGATES = get_env(
    "CELERY_TASK_EAGER_PROPAGATES", default=True, cast=bool
)
CELERY_TIMEZONE = get_env("CELERY_TIMEZONE", default="UTC")
CELERY_EMAIL_QUEUE = get_env("CELERY_EMAIL_QUEUE", default="email")
CELERY_TASK_IGNORE_RESULT = get_env(
    "CELERY_TASK_IGNORE_RESULT", default=True, cast=bool
)
CELERY_TASK_STORE_EAGER_RESULT = get_env(
    "CELERY_TASK_STORE_EAGER_RESULT", default=False, cast=bool
)
SESSION_MAX_AGE_DAYS = get_env("SESSION_MAX_AGE_DAYS", default=14, cast=int)
SESSION_COOKIE_AGE = max(1, int(SESSION_MAX_AGE_DAYS)) * 24 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

ORDER_AUTO_CANCEL_HOURS = get_env("ORDER_AUTO_CANCEL_HOURS", default=12, cast=int)
MANUAL_PENDING_AUTO_COMPLETE_HOURS = get_env(
    "MANUAL_PENDING_AUTO_COMPLETE_HOURS", default=48, cast=int
)
RESERVATION_TTL_MINUTES = get_env("RESERVATION_TTL_MINUTES", default=120, cast=int)
PAYMENT_POLL_BATCH_LIMIT = get_env("PAYMENT_POLL_BATCH_LIMIT", default=720, cast=int)
TELEGRAM_NOTIFY_RETRY_BATCH_LIMIT = get_env(
    "TELEGRAM_NOTIFY_RETRY_BATCH_LIMIT", default=200, cast=int
)
CELERY_TASK_ROUTES = {
    "apps.notifications.tasks.send_registration_info_email_task": {
        "queue": CELERY_EMAIL_QUEUE
    },
    "apps.notifications.tasks.send_password_reset_email_task": {
        "queue": CELERY_EMAIL_QUEUE
    },
    "apps.notifications.tasks.send_order_completed_email_task": {
        "queue": CELERY_EMAIL_QUEUE
    },
    "apps.orders.tasks.reconcile_waiting_stock_orders_task": {
        "queue": CELERY_EMAIL_QUEUE
    },
    "apps.orders.tasks.cancel_stale_unpaid_orders_task": {"queue": CELERY_EMAIL_QUEUE},
    "apps.orders.tasks.complete_stale_manual_pending_orders_task": {
        "queue": CELERY_EMAIL_QUEUE
    },
    "apps.orders.tasks.poll_awaiting_order_payments_task": {
        "queue": CELERY_EMAIL_QUEUE
    },
    "apps.orders.tasks.retry_due_order_telegram_notifications_task": {
        "queue": CELERY_EMAIL_QUEUE
    },
    "apps.core.tasks.cleanup_expired_sessions_task": {"queue": CELERY_EMAIL_QUEUE},
}
CELERY_BEAT_SCHEDULE = {
    "orders-reconcile-waiting-stock-every-30-seconds": {
        "task": "apps.orders.tasks.reconcile_waiting_stock_orders_task",
        "schedule": 30.0,
    },
    "orders-cancel-stale-unpaid-every-10-minutes": {
        "task": "apps.orders.tasks.cancel_stale_unpaid_orders_task",
        "schedule": 600.0,
    },
    "orders-complete-stale-manual-pending-every-30-minutes": {
        "task": "apps.orders.tasks.complete_stale_manual_pending_orders_task",
        "schedule": 1800.0,
    },
    "payments-poll-awaiting-orders-every-5-minutes": {
        "task": "apps.orders.tasks.poll_awaiting_order_payments_task",
        "schedule": 300.0,
    },
    "orders-telegram-notify-retry-every-30-seconds": {
        "task": "apps.orders.tasks.retry_due_order_telegram_notifications_task",
        "schedule": 30.0,
    },
    # django_session rows past expire_date (see SESSION_MAX_AGE_DAYS).
    "sessions-cleanup-expired-daily": {
        "task": "apps.core.tasks.cleanup_expired_sessions_task",
        "schedule": 86400.0,
    },
}

# NOWPayments — secrets in .env; redirect targets = PUBLIC_SITE_URL + relative paths below (no duplicate full URLs in .env).
PUBLIC_SITE_URL = get_env("PUBLIC_SITE_URL", default="http://127.0.0.1:8000")
# Shop display / checkout currency (amounts stored as Decimal; code shown in UI).
SHOP_CURRENCY = get_env("SHOP_CURRENCY", default="USD")
NOWPAYMENTS_API_KEY_SECRET = get_env(
    "NOWPAYMENTS_API_KEY_SECRET", default=""
) or get_env("NOWPAYMENTS_API_KEY", default="")
NOWPAYMENTS_IPN_SECRET = get_env("NOWPAYMENTS_IPN_SECRET", default="")
NOWPAYMENTS_BASE_URL = get_env(
    "NOWPAYMENTS_BASE_URL", default="https://api.nowpayments.io/v1"
)
NOWPAYMENTS_MIN_AMOUNT_FIAT = get_env("NOWPAYMENTS_MIN_AMOUNT_FIAT", default="1.0")
NOWPAYMENTS_SUPPORTED_FIAT = get_env(
    "NOWPAYMENTS_SUPPORTED_FIAT", default="rub,usd,eur", cast=Csv()
)
# Relative paths (start with /), joined with PUBLIC_SITE_URL in code.
NOWPAYMENTS_DEFAULT_SUCCESS_REL_PATH = "/"
NOWPAYMENTS_DEFAULT_CANCEL_REL_PATH = "/"

# RollyPay (https://rollypay.io) — X-API-Key + X-Nonce; webhooks HMAC-SHA256(signing_secret, timestamp + "." + body).
ROLLYPAY_API_KEY = get_env("ROLLYPAY_API_KEY", default="")
ROLLYPAY_SIGNING_SECRET = get_env("ROLLYPAY_SIGNING_SECRET", default="")
ROLLYPAY_TERMINAL_ID = get_env("ROLLYPAY_TERMINAL_ID", default="")
ROLLYPAY_BASE_URL = get_env("ROLLYPAY_BASE_URL", default="https://rollypay.io")
ROLLYPAY_MIN_AMOUNT_RUB = get_env("ROLLYPAY_MIN_AMOUNT_RUB", default="10.0")
ROLLYPAY_DEFAULT_SUCCESS_REL_PATH = "/"
ROLLYPAY_DEFAULT_FAIL_REL_PATH = "/"

# Enot.io — x-api-key (shop secret); webhook HMAC uses additional shop key (ENOT_WEBHOOK_SECRET).
ENOT_SHOP_ID = get_env("ENOT_SHOP_ID", default="")
ENOT_API_KEY = get_env("ENOT_API_KEY", default="")
ENOT_WEBHOOK_SECRET = get_env("ENOT_WEBHOOK_SECRET", default="")
ENOT_BASE_URL = get_env("ENOT_BASE_URL", default="https://api.enot.io")
ENOT_MIN_AMOUNT_RUB = get_env("ENOT_MIN_AMOUNT_RUB", default="10.0")
ENOT_INVOICE_EXPIRE_MINUTES = get_env("ENOT_INVOICE_EXPIRE_MINUTES", default="300")
ENOT_DEFAULT_SUCCESS_REL_PATH = "/"
ENOT_DEFAULT_FAIL_REL_PATH = "/"

BALANCE_TOPUP_SUCCESS_REL_PATH = "/accounts/balance/topup-result/?topup=success"
BALANCE_TOPUP_CANCEL_REL_PATH = "/accounts/balance/topup-result/?topup=cancel"
# Provider on/off and min/max RUB per provider: Django admin → Payment provider settings.

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.core.apps.CoreConfig",
    "apps.catalog.apps.CatalogConfig",
    "apps.accounts.apps.AccountsConfig",
    "apps.notifications.apps.NotificationsConfig",
    "apps.orders.apps.OrdersConfig",
    "apps.payments.apps.PaymentsConfig",
]

try:
    import whitenoise  # noqa: F401

    WHITENOISE_AVAILABLE = True
except ImportError:
    WHITENOISE_AVAILABLE = False

_MIDDLEWARE_BASE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "apps.core.middleware.MaintenanceModeMiddleware",
    "apps.accounts.middleware.AccountsTrackingMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if WHITENOISE_AVAILABLE:
    MIDDLEWARE = [
        _MIDDLEWARE_BASE[0],
        "whitenoise.middleware.WhiteNoiseMiddleware",
        *_MIDDLEWARE_BASE[1:],
    ]
else:
    import warnings

    warnings.warn(
        "whitenoise is not installed; rebuild the web image. Static files may 404 when DEBUG=False.",
        stacklevel=1,
    )
    MIDDLEWARE = list(_MIDDLEWARE_BASE)

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.ui",
                "apps.core.context_processors.catalog_search_extras",
                "apps.core.context_processors.shop_runtime_flags",
                "apps.accounts.context_processors.turnstile",
                "apps.accounts.context_processors.account_balance_header",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DB_ENGINE = str(get_env("DB_ENGINE", default="sqlite") or "sqlite").strip().lower()
if DB_ENGINE == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": get_env("POSTGRES_DB", default="freestorex"),
            "USER": get_env("POSTGRES_USER", default="postgres"),
            "PASSWORD": get_env("POSTGRES_PASSWORD", default="postgres"),
            "HOST": get_env("POSTGRES_HOST", default="postgres"),
            "PORT": get_env("POSTGRES_PORT", default="5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": get_env("SQLITE_NAME", default=str(BASE_DIR / "db.sqlite3")),
        }
    }

# Used for login attempt tracking / basic rate limits
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "freestorex-cache",
    }
}

REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_RATES": {
        "auth_login": "60/minute",
        "auth_register": "30/minute",
        "auth_password_reset": "12/minute",
        "auth_password_reset_confirm": "45/minute",
    },
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = ROOT_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
if not DEBUG and WHITENOISE_AVAILABLE:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"
MEDIA_URL = "/media/"
MEDIA_ROOT = ROOT_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Route all std logging through loguru
LOGGING_CONFIG = None

configure_loguru(root_dir=ROOT_DIR, debug=bool(DEBUG))

# Sentry (optional): set SENTRY_DSN in env to enable.
SENTRY_DSN = get_env("SENTRY_DSN", default="")
SENTRY_TRACES_SAMPLE_RATE = get_env(
    "SENTRY_TRACES_SAMPLE_RATE", default=0.0, cast=float
)
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.redis import RedisIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration(), CeleryIntegration(), RedisIntegration()],
            traces_sample_rate=float(SENTRY_TRACES_SAMPLE_RATE or 0.0),
            send_default_pii=False,
            environment=("development" if bool(DEBUG) else "production"),
        )
    except Exception:
        # Keep app boot resilient if sentry-sdk isn't installed yet.
        pass

if not DEBUG:
    from django.core.exceptions import ImproperlyConfigured

    _sk = (SECRET_KEY or "").strip()
    if _sk in {"", "django-insecure-change-me"}:
        raise ImproperlyConfigured(
            "SECRET_KEY must be set to a strong unique value when DEBUG is False."
        )
