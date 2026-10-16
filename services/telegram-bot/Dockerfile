FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/services/telegram-bot

COPY services/telegram-bot/requirements.txt .
RUN pip install -r requirements.txt

COPY services/telegram-bot/ .
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/logs \
    && chown -R app:app /app

USER app

CMD ["python", "-m", "bot.main"]
