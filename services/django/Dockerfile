FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/services/django

COPY services/django/requirements.txt .
RUN pip install -r requirements.txt

COPY services/django/ .
RUN python manage.py collectstatic --noinput \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /app/logs /app/media \
    && chown -R app:app /app

USER app
EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--config", "gunicorn.conf.py"]
