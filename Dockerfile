FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/bot

# Dependencies go first so that code changes do not reinstall them.
COPY requirements.lock ./
RUN pip install -r requirements.lock

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

RUN useradd --create-home --uid 10001 bot
USER bot

# exec makes python PID 1's child replace the shell, so `docker compose stop`
# delivers SIGTERM to the bot and polling shuts down gracefully.
CMD ["sh", "-c", "alembic upgrade head && exec python -m app"]
