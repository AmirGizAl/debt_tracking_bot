"""Configuration (TZ 15.2): owners come from OWNER_TELEGRAM_IDS."""

import pytest
from pydantic import ValidationError

from app.config import Settings

BASE = {"_env_file": None, "bot_token": "123:abc", "database_url": "postgresql://x"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("111111111", (111111111,)),
        ("111111111,222222222", (111111111, 222222222)),
        (" 111 , 222 , 111 ", (111, 222)),  # spaces and repeats are fine
    ],
)
def test_owner_ids(monkeypatch: pytest.MonkeyPatch, raw: str, expected: tuple[int, ...]) -> None:
    monkeypatch.setenv("OWNER_TELEGRAM_IDS", raw)

    assert Settings(**BASE).owner_telegram_ids == expected


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "OWNER_TELEGRAM_IDS is empty"),
        (" , ", "OWNER_TELEGRAM_IDS is empty"),
        ("111,-5", "positive Telegram user ids"),
        ("111,abc", "valid integer"),
    ],
)
def test_wrong_owner_ids_stop_the_start(
    monkeypatch: pytest.MonkeyPatch, raw: str, message: str
) -> None:
    monkeypatch.setenv("OWNER_TELEGRAM_IDS", raw)

    with pytest.raises(ValidationError, match=message):
        Settings(**BASE)


def test_owner_ids_are_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OWNER_TELEGRAM_IDS", raising=False)
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "111")  # the variable of version 1 is not read

    with pytest.raises(ValidationError, match="owner_telegram_ids"):
        Settings(**BASE)
