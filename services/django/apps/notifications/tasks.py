from __future__ import annotations

from celery import shared_task

from .mailing import (
    send_order_completed_email,
    send_password_reset_email,
    send_registration_info_email,
)


@shared_task
def send_registration_info_email_task(recipient: str) -> None:
    send_registration_info_email(recipient=recipient)


@shared_task
def send_password_reset_email_task(recipient: str, reset_link: str) -> None:
    send_password_reset_email(recipient=recipient, reset_link=reset_link)


@shared_task
def send_order_completed_email_task(
    recipient: str,
    order_public_id: int,
    order_url: str,
    order_lines: list[str],
    is_guest_order: bool = False,
    is_manual_order: bool = False,
) -> None:
    send_order_completed_email(
        recipient=recipient,
        order_public_id=order_public_id,
        order_url=order_url,
        order_lines=order_lines,
        is_guest_order=is_guest_order,
        is_manual_order=is_manual_order,
    )
