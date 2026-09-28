"""Moscow time everywhere (customer request of 28.09.2026, overrides Asia/Bishkek of TZ 7.6)."""

import logging
from datetime import UTC, datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import RecordAction, RecordCb
from app.config import Settings
from app.db.models import User
from app.domain.operations import OperationType
from app.logging import LOG_FORMAT, ZoneFormatter
from tests.bot.harness import BOT_TOKEN, UserClient
from tests.factories import make_client, make_operation

MOSCOW = ZoneInfo("Europe/Moscow")


def test_moscow_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TZ", raising=False)

    settings = Settings(
        _env_file=None, bot_token=BOT_TOKEN, owner_telegram_id=1, database_url="postgresql://x"
    )

    assert settings.tz == "Europe/Moscow"
    assert settings.zone == MOSCOW


def test_log_timestamps_are_moscow_time() -> None:
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "hello", None, None)
    record.created = datetime(2026, 9, 27, 21, 30, tzinfo=UTC).timestamp()
    record.msecs = 0

    line = ZoneFormatter(LOG_FORMAT, MOSCOW).format(record)

    assert line.startswith("2026-09-28 00:30:00.000+0300 INFO")


async def test_record_card_shows_moscow_time(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    client = await make_client(session, owner_user, "Тимур")
    operation = await make_operation(
        session,
        owner_user,
        client,
        OperationType.BORROW,
        "100",
        created_at=datetime(2026, 9, 27, 21, 30, tzinfo=UTC),
    )
    await owner_client.send("/menu")

    await owner_client.press(
        RecordCb(action=RecordAction.OPEN, operation_id=operation.id).pack(), owner_client.last
    )

    assert "внесено 28.09.2026 00:30" in owner_client.last.text  # 21:30 UTC = 00:30 MSK


async def test_report_is_stamped_with_moscow_time(owner_client: UserClient) -> None:
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_REPORTS)
    await owner_client.click(texts.BTN_REPORT_DEBTS)
    await owner_client.click(texts.BTN_EXCEL)

    document = [m for m in owner_client.bot_messages if m.document_data][-1]
    assert document.document_data is not None
    sheet = load_workbook(BytesIO(document.document_data)).active
    assert sheet is not None
    stamp = next(
        str(cell) for (cell,) in sheet.iter_rows(max_col=1, values_only=True)
        if str(cell).startswith("Сформирован: ")
    )  # fmt: skip
    generated = datetime.strptime(stamp, "Сформирован: %d.%m.%Y %H:%M").replace(tzinfo=MOSCOW)
    assert abs(datetime.now(MOSCOW) - generated) < timedelta(minutes=2)
