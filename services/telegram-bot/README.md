# Telegram Bot Service

This service runs a standalone Telegram bot for store operations.

## Stack

- aiogram 3.26.0
- loguru

## Logs

- Root folder: `logs/telegram-bot`
- App log: `logs/telegram-bot/app_YYYY-MM-DD.log`
- Error log: `logs/telegram-bot/error_YYYY-MM-DD.log`

## Backend callback (manual order «Завершить» button)

The bot calls Django `POST /internal/bot/manual-orders/complete/` with header `x-api-key: BOT_INTERNAL_API_KEY`.

Use `PUBLIC_SITE_URL` as the Django base (must be reachable from this process, e.g. `http://web:8000` in Docker or your public HTTPS URL). Same `BOT_INTERNAL_API_KEY` as Django.

## Required env vars

- `PUBLIC_SITE_URL` (Django origin for internal HTTP callbacks)
- `BOT_INTERNAL_API_KEY` (must match Django)
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_BOT_USERNAME`
- `TG_FORUM_CHAT_ID`
- `TG_TOPIC_BOT_START`
- `TG_TOPIC_MANUAL_ORDERS`
- `TG_TOPIC_PREORDERS`
- `TG_TOPIC_ERRORS`
- `TG_TOPIC_LOGS`
- `TG_TOPIC_SIGNUPS`
- `TG_TOPIC_TOPUPS`
- `TG_TOPIC_ORDERS`

## Database mode

- Bot uses the same database env contract as Django:
  - `DB_ENGINE` (`sqlite` or `postgres`)
  - `SQLITE_NAME`
  - `POSTGRES_DB`
  - `POSTGRES_USER`
  - `POSTGRES_PASSWORD`
  - `POSTGRES_HOST`
  - `POSTGRES_PORT`
- If PostgreSQL config is incomplete (or `DB_ENGINE != postgres`), bot uses sqlite from:
  - `SQLITE_NAME` (if set)
  - otherwise default Django sqlite path: `services/django/db.sqlite3`

## Local run

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r services/telegram-bot/requirements.txt
python -m bot.main
```
