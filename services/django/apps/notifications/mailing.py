from __future__ import annotations

import smtplib
from urllib.parse import urlparse

from django.conf import settings
from django.core.mail import send_mail
from loguru import logger


def send_registration_info_email(recipient: str) -> None:
    recipient = (recipient or "").strip()
    if not recipient:
        return
    subject = "Welcome"
    body = (
        "Thanks for signing up.\n\n"
        "Your account has been created. Enjoy shopping!"
    )
    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[recipient],
        fail_silently=False,
    )


def send_password_reset_email(recipient: str, reset_link: str) -> None:
    recipient = (recipient or "").strip()
    if not recipient or not reset_link:
        return
    subject = "Password reset"
    body = (
        "You requested a password reset.\n"
        f"Open this link to set a new password:\n{reset_link}\n\n"
        "This link is valid for 12 hours.\n\n"
        "If you did not request this, you can ignore this email."
    )
    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[recipient],
        fail_silently=False,
    )


def send_order_completed_email(
    *,
    recipient: str,
    order_public_id: int,
    order_url: str,
    order_lines: list[str],
    is_guest_order: bool = False,
    is_manual_order: bool = False,
) -> None:
    recipient = (recipient or "").strip()
    if not recipient:
        return
    subject = f"Order {order_public_id} completed"
    lines = [x for x in (order_lines or []) if str(x).strip()]
    details_block = "\n".join(lines) if lines else f"Order #{order_public_id}"
    parsed = urlparse(order_url or "")
    base_url = (
        f"{parsed.scheme}://{parsed.netloc}"
        if parsed.scheme and parsed.netloc
        else str(getattr(settings, "PUBLIC_SITE_URL", "http://127.0.0.1:8000")).rstrip(
            "/"
        )
    )
    guest_hint = ""
    if is_guest_order:
        guest_hint = (
            "\n\n"
            f"Create an account and sign in at {base_url}/accounts/login/ "
            "to keep permanent access to your orders."
        )
    manual_support_hint = ""
    if is_manual_order:
        manual_support_hint = (
            "\n\n"
            "If you have questions, contact support\n"
            "https://github.com/fpoweredd/demo-freestore"
        )
    body = (
        f"Order #{order_public_id}:\n"
        f"{details_block}\n\n"
        "Thanks for your purchase!\n"
        f"Order link: {order_url}"
        f"{guest_hint}"
        f"{manual_support_hint}"
    )
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[recipient],
            fail_silently=False,
        )
    except smtplib.SMTPDataError as exc:
        code = getattr(exc, "smtp_code", None)
        msg = (
            (getattr(exc, "smtp_error", b"") or b"")
            .decode("utf-8", errors="ignore")
            .lower()
        )
        if code == 450 and "suppressed" in msg:
            logger.warning(
                "order_completed_email_suppressed recipient={} order_public_id={}",
                recipient,
                order_public_id,
            )
            return
        if code == 450 and ("unique recipients limit" in msg or "ms42225" in msg):
            logger.warning(
                "order_completed_email_trial_limit recipient={} order_public_id={} smtp_code={} smtp_error={}",
                recipient,
                order_public_id,
                code,
                msg,
            )
            return
        raise
