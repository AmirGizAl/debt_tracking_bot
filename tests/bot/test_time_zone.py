"""Moscow time everywhere (customer's request, kept for version 2 instead of Asia/Bishkek)."""

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.logging import LOG_FORMAT, ZoneFormatter
from tests.bot.harness import BOT_TOKEN

MOSCOW = ZoneInfo("Europe/Moscow")


def test_moscow_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TZ", raising=False)

    settings = Settings(
        _env_file=None, bot_token=BOT_TOKEN, owner_telegram_ids="1", database_url="postgresql://x"
    )

    assert settings.tz == "Europe/Moscow"
    assert settings.zone == MOSCOW


def test_log_timestamps_are_moscow_time() -> None:
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "hello", None, None)
    record.created = datetime(2026, 9, 27, 21, 30, tzinfo=UTC).timestamp()
    record.msecs = 0

    line = ZoneFormatter(LOG_FORMAT, MOSCOW).format(record)

    assert line.startswith("2026-09-28 00:30:00.000+0300 INFO")
