from __future__ import annotations

from copy import deepcopy

# Central place for UI labels / strings that are used across templates and views.
# Override per-product-card labels via ProductCard.ui_labels (JSONField).
UI_TEXT: dict = {
    "common": {
        "auth": {
            "login_title": "Sign in",
            "register_title": "Sign up",
            "password_reset_title": "Reset password",
            "create_account": "Create account",
            "forgot_password": "Forgot password?",
            "btn_login": "Sign in",
            "btn_register": "Create account",
            "btn_reset_request": "Reset password",
            "label_email": "Email",
            "label_password": "Password",
            "label_password_confirm": "Confirm password",
            "label_telegram_optional": "Telegram (optional)",
            "label_token": "Token",
            "label_new_password": "New password",
        }
    },
    "accounts": {
        "nav": {
            "top_up": "Top up balance",
            "profile": "My profile",
            "orders": "My orders",
            "logout": "Log out",
            "login": "Sign in",
        },
        "messages": {
            "oauth_google_failed": "Google sign-in failed.",
            "oauth_telegram_failed": "Telegram sign-in failed.",
            "login_success": "You are signed in.",
            "login_failed": "Invalid email or password.",
            "register_success": "Registration complete.",
            "logout_success": "You are signed out.",
            "pwdreset_requested": "If that email exists, we will send reset instructions.",
            "pwdreset_requested_wait_3m": "Email already sent. Please wait before requesting again.",
            "pwdreset_requested_wait_15m": "You already requested a reset for this account. Wait 15 minutes.",
            "pwdreset_requested_later": "Please try again later.",
            "pwdreset_done_login": "Password updated.",
            "pwdreset_invalid": "Invalid or expired token.",
            "pwdreset_link_invalid": "This link is invalid or expired.",
            "stepup_success": "Verified. You are signed in.",
            "stepup_invalid_password": "Invalid password.",
            "profile_updated": "Profile updated.",
            "form_fix_errors": "Please fix the errors in the form.",
            "password_updated": "Password updated.",
            "password_set": "Password set.",
            "unknown_action": "Unknown action.",
        },
    },
    "catalog": {
        "product_labels_default": {
            "platform": "Platform",
            "region": "Region",
            "nominal": "Denomination",
            "variant": "Variant",
            "sku": "SKU",
            "fulfillment_instant": "Instant delivery",
            "fulfillment_manual": "Fast and secure",
            "fulfillment_prefix": "⏱",
            "order_data": "Order details",
            "buyers_suffix": "buyers",
            "payment_method": "Payment method",
            "promo_code": "Promo code",
            "price": "Price",
            "old_price": "Was",
            "total": "Total",
        }
    },
}

PROVIDER_UI_LABELS: dict[str, str] = {
    "nowpayments": "Crypto",
    "rollypay": "SBP (backup)",
    "enot": "Card / SBP",
    "stub": "Stripe",
}


def ui_text() -> dict:
    """Return a safe copy so callers can merge/modify locally."""
    return deepcopy(UI_TEXT)
