from __future__ import annotations

import secrets
from typing import Any

import uvicorn
from aiogram import Bot
from fastapi import FastAPI, Header, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field

from bot.admin_handlers.order_notifications import (
    edit_preorder_notification_to_completed,
    send_manual_order_notification_to_topic,
    send_order_notification_to_topic,
    send_payment_error_to_logs_topic,
    send_preorder_fulfilled_notification_to_topic,
    send_preorder_paid_notification_to_topic,
    send_signup_notification_to_topic,
    send_topup_notification_to_topic,
)
from bot.config import BotSettings

app = FastAPI(title="Freestore Telegram Bot Internal API")

_runtime_bot: Bot | None = None
_runtime_settings: BotSettings | None = None


def _internal_api_key_valid(*, provided: str | None, expected: str) -> bool:
    if not expected:
        return False
    try:
        return secrets.compare_digest(provided or "", expected)
    except (TypeError, ValueError):
        return False


def bind_runtime(*, bot: Bot, settings: BotSettings) -> None:
    global _runtime_bot, _runtime_settings
    _runtime_bot = bot
    _runtime_settings = settings


def _require_runtime() -> tuple[Bot, BotSettings]:
    if _runtime_bot is None or _runtime_settings is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot runtime is not ready",
        )
    return _runtime_bot, _runtime_settings


class OrderItemPayload(BaseModel):
    product_name: str = ""
    quantity: int = 1
    sku_params: dict[str, Any] = Field(default_factory=dict)
    sku_params_labeled: list[dict[str, str]] = Field(default_factory=list)
    sku_line: str = ""


class OrderNotifyPayload(BaseModel):
    order_public_id: int
    user_public_id: str | None = None
    user_email: str | None = None
    order_email: str | None = None
    total_rub: str
    payment_method: str | None = None
    wallet_balance_after_rub: str | None = None
    tg_auth: str | None = None
    tg_handler: str | None = None
    role: str | None = None
    reg_geo: str | None = None
    locale: str | None = None
    utm_params: dict[str, str] = Field(default_factory=dict)
    items: list[OrderItemPayload] = Field(default_factory=list)


class PreOrderNotifyPayload(OrderNotifyPayload):
    preorder_public_id: int
    preorder_status: str | None = None
    admin_upload_url: str | None = None
    required_qty_total: int | None = None  # legacy, ignored by notifier
    edit_chat_id: int | None = None
    edit_message_id: int | None = None
    previous_text: str | None = None


class SignupNotifyPayload(BaseModel):
    user_public_id: str
    user_email: str | None = None
    registration_method: str
    reg_geo: str | None = None
    locale: str | None = None
    registration_ip: str | None = None
    utm_params: dict[str, str] = Field(default_factory=dict)
    tg_auth: str | None = None
    tg_handler: str | None = None


class TopupNotifyPayload(BaseModel):
    topup_public_id: int
    payment_id: str
    provider_id: str
    amount_rub: str
    currency: str = "RUB"
    status: str
    success: bool
    reason: str | None = None
    user_public_id: str | None = None
    user_email: str | None = None


class PaymentErrorPayload(BaseModel):
    provider_id: str
    error_code: str
    error_message: str
    context: dict[str, str] = Field(default_factory=dict)


class ManualOrderNotifyPayload(OrderNotifyPayload):
    created_at: str | None = None
    guest_email: str | None = None


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.post("/internal/orders/notify")
async def notify_order(
    payload: OrderNotifyPayload,
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> dict[str, bool]:
    bot, settings = _require_runtime()
    if not _internal_api_key_valid(
        provided=x_api_key, expected=settings.internal_api_key
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    try:
        await send_order_notification_to_topic(
            bot=bot,
            settings=settings,
            order_public_id=payload.order_public_id,
            user_public_id=payload.user_public_id,
            user_email=payload.user_email,
            order_email=payload.order_email,
            total_rub=payload.total_rub,
            payment_method=payload.payment_method,
            wallet_balance_after_rub=payload.wallet_balance_after_rub,
            tg_auth=payload.tg_auth,
            tg_handler=payload.tg_handler,
            role=payload.role,
            reg_geo=payload.reg_geo,
            locale=payload.locale,
            utm_params=payload.utm_params,
            items=[item.model_dump() for item in payload.items],
        )
    except Exception:
        logger.exception(
            "notify_order_failed order_public_id={}", payload.order_public_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to notify order",
        ) from None

    return {"ok": True}


@app.post("/internal/manual-orders/notify")
async def notify_manual_order(
    payload: ManualOrderNotifyPayload,
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> dict[str, Any]:
    bot, settings = _require_runtime()
    if not _internal_api_key_valid(
        provided=x_api_key, expected=settings.internal_api_key
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    try:
        result = await send_manual_order_notification_to_topic(
            bot=bot,
            settings=settings,
            order_public_id=payload.order_public_id,
            user_public_id=payload.user_public_id,
            user_email=payload.user_email,
            order_email=payload.order_email,
            guest_email=payload.guest_email,
            total_rub=payload.total_rub,
            payment_method=payload.payment_method,
            wallet_balance_after_rub=payload.wallet_balance_after_rub,
            tg_auth=payload.tg_auth,
            tg_handler=payload.tg_handler,
            role=payload.role,
            reg_geo=payload.reg_geo,
            locale=payload.locale,
            utm_params=payload.utm_params,
            items=[item.model_dump() for item in payload.items],
        )
    except Exception:
        logger.exception(
            "notify_manual_order_failed order_public_id={}", payload.order_public_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to notify manual order",
        ) from None

    if not result:
        return {"ok": True}
    chat_id, message_id = result
    return {"ok": True, "chat_id": chat_id, "message_id": message_id}

@app.post("/internal/preorders/notify-paid")
async def notify_preorder_paid(
    payload: PreOrderNotifyPayload,
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> dict[str, Any]:
    bot, settings = _require_runtime()
    if not _internal_api_key_valid(
        provided=x_api_key, expected=settings.internal_api_key
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    try:
        result = await send_preorder_paid_notification_to_topic(
            bot=bot,
            settings=settings,
            preorder_public_id=payload.preorder_public_id,
            order_public_id=payload.order_public_id,
            user_public_id=payload.user_public_id,
            user_email=payload.user_email,
            order_email=payload.order_email,
            total_rub=payload.total_rub,
            payment_method=payload.payment_method,
            wallet_balance_after_rub=payload.wallet_balance_after_rub,
            tg_auth=payload.tg_auth,
            tg_handler=payload.tg_handler,
            role=payload.role,
            reg_geo=payload.reg_geo,
            locale=payload.locale,
            utm_params=payload.utm_params,
            admin_upload_url=payload.admin_upload_url,
            items=[item.model_dump() for item in payload.items],
        )
    except Exception:
        logger.exception(
            "notify_preorder_paid_failed preorder_public_id={}",
            payload.preorder_public_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to notify preorder",
        ) from None
    if not result:
        return {"ok": True}
    chat_id, message_id, text = result
    return {
        "ok": True,
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }


@app.post("/internal/preorders/notify-fulfilled")
async def notify_preorder_fulfilled(
    payload: PreOrderNotifyPayload,
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> dict[str, bool]:
    bot, settings = _require_runtime()
    if not _internal_api_key_valid(
        provided=x_api_key, expected=settings.internal_api_key
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    try:
        if (
            payload.edit_chat_id is not None
            and payload.edit_message_id is not None
            and (payload.previous_text or "").strip()
        ):
            await edit_preorder_notification_to_completed(
                bot=bot,
                chat_id=int(payload.edit_chat_id),
                message_id=int(payload.edit_message_id),
                previous_text=str(payload.previous_text),
            )
        else:
            await send_preorder_fulfilled_notification_to_topic(
                bot=bot,
                settings=settings,
                preorder_public_id=payload.preorder_public_id,
                order_public_id=payload.order_public_id,
                user_public_id=payload.user_public_id,
                user_email=payload.user_email,
                order_email=payload.order_email,
                tg_auth=payload.tg_auth,
                tg_handler=payload.tg_handler,
                items=[item.model_dump() for item in payload.items],
            )
    except Exception:
        logger.exception(
            "notify_preorder_fulfilled_failed preorder_public_id={}",
            payload.preorder_public_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to notify preorder fulfilled",
        ) from None
    return {"ok": True}


@app.post("/internal/signups/notify")
async def notify_signup(
    payload: SignupNotifyPayload,
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> dict[str, bool]:
    bot, settings = _require_runtime()
    if not _internal_api_key_valid(
        provided=x_api_key, expected=settings.internal_api_key
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    try:
        await send_signup_notification_to_topic(
            bot=bot,
            settings=settings,
            user_public_id=payload.user_public_id,
            user_email=payload.user_email,
            registration_method=payload.registration_method,
            reg_geo=payload.reg_geo,
            locale=payload.locale,
            registration_ip=payload.registration_ip,
            utm_params=payload.utm_params,
            tg_auth=payload.tg_auth,
            tg_handler=payload.tg_handler,
        )
    except Exception:
        logger.exception(
            "notify_signup_failed user_public_id={}",
            payload.user_public_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to notify signup",
        ) from None
    return {"ok": True}


@app.post("/internal/topups/notify")
async def notify_topup(
    payload: TopupNotifyPayload,
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> dict[str, bool]:
    bot, settings = _require_runtime()
    if not _internal_api_key_valid(
        provided=x_api_key, expected=settings.internal_api_key
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    try:
        await send_topup_notification_to_topic(
            bot=bot,
            settings=settings,
            topup_public_id=payload.topup_public_id,
            payment_id=payload.payment_id,
            provider_id=payload.provider_id,
            amount_rub=payload.amount_rub,
            currency=payload.currency,
            status=payload.status,
            success=payload.success,
            reason=payload.reason,
            user_public_id=payload.user_public_id,
            user_email=payload.user_email,
        )
    except Exception:
        logger.exception(
            "notify_topup_failed topup_public_id={}",
            payload.topup_public_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to notify topup",
        ) from None
    return {"ok": True}


@app.post("/internal/payments/errors")
async def notify_payment_error(
    payload: PaymentErrorPayload,
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> dict[str, bool]:
    bot, settings = _require_runtime()
    if not _internal_api_key_valid(
        provided=x_api_key, expected=settings.internal_api_key
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    try:
        await send_payment_error_to_logs_topic(
            bot=bot,
            settings=settings,
            provider_id=payload.provider_id,
            error_code=payload.error_code,
            error_message=payload.error_message,
            context=payload.context,
        )
    except Exception:
        logger.exception(
            "notify_payment_error_failed code={}",
            payload.error_code,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to notify payment error",
        ) from None
    return {"ok": True}


async def run_api_server(settings: BotSettings) -> None:
    host = "0.0.0.0"
    port = 8091
    bind = (settings.internal_api_bind or "").strip()
    if bind:
        if ":" in bind:
            raw_host, raw_port = bind.rsplit(":", 1)
            host = (raw_host or host).strip()
            try:
                port = int(raw_port.strip())
            except Exception:
                port = port
        else:
            host = bind

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()
