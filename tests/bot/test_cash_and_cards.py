"""Cash, adjustments, record cards, history and cancelling (TZ 8, 12.5-12.7, 12.10).

Covers TZ 15.1 scenarios 1, 10 and 12 end to end through the bot.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import CashAction, CashCb, RecordAction, RecordCb
from app.db.models import CashAdjustment, Client, Operation, User
from app.domain.currency import Currency
from app.domain.dates import format_date, format_short_date
from app.domain.operations import OperationType
from app.services import balances, cash, users
from tests.bot.harness import Harness, UserClient
from tests.bot.records import new_debt, repay_same, save, today_text
from tests.factories import make_client
from tests.services.accounting import TODAY, adjust, record, reverse

USD, RUB, KGS = Currency.USD, Currency.RUB, Currency.KGS
HELPER_TG_ID = 2002


async def adjust_via_ui(
    client: UserClient, currency: str, direction: str, amount: str, reason: str
) -> None:
    await client.send("/menu")
    await client.click(texts.BTN_CASH)
    await client.click(texts.BTN_ADJUST)
    await client.click(currency)
    await client.click(direction)
    await client.send(amount)
    await client.send(reason)


async def count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def client_named(session: AsyncSession, name: str) -> Client:
    client = await session.scalar(select(Client).where(Client.name == name))
    assert client is not None
    return client


@pytest.fixture
async def aigul(harness: Harness, session: AsyncSession, owner_user: User) -> UserClient:
    await users.add_helper(session, owner_user, "aigul_k")
    helper = harness.user(HELPER_TG_ID, username="aigul_k", first_name="Айгуль")
    await helper.send("/start")
    return helper


# --- cash --------------------------------------------------------------------------------------


async def test_scenario_1_opening_balances(owner_client: UserClient, session: AsyncSession) -> None:
    for currency, amount in (
        ("KGS", "300 000"),
        ("USD", "10 000"),
        ("EUR", "2 000"),
        ("RUB", "500 000"),
        ("KZT", "1 000 000"),
    ):
        await adjust_via_ui(
            owner_client, currency, texts.BTN_ADD_MONEY, amount, "Остаток на начало работы"
        )
        assert owner_client.last.text.startswith("Проверьте корректировку")
        assert await save(owner_client) == f"Корректировка сохранена.\nВ кассе {currency}: {amount}"

    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_CASH)

    assert owner_client.last.text == (
        "Касса\nKGS: 300 000\nUSD: 10 000\nEUR: 2 000\nRUB: 500 000\nKZT: 1 000 000"
    )
    assert owner_client.last.button_texts == [texts.BTN_MOVEMENTS, texts.BTN_ADJUST, texts.BTN_HOME]


async def test_cash_screen_shows_zeros(owner_client: UserClient) -> None:
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_CASH)

    assert owner_client.last.text == "Касса\nKGS: 0\nUSD: 0\nEUR: 0\nRUB: 0\nKZT: 0"


async def test_adjustment_confirmation_and_removal(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await adjust(session, owner_user, "9400")
    await adjust_via_ui(owner_client, "USD", texts.BTN_REMOVE_MONEY, "500", "Личные расходы")

    assert owner_client.last.text == "\n".join(
        [
            "Проверьте корректировку",
            "Касса: USD",
            "Изменение: −500 USD",
            "Причина: Личные расходы",
            "",
            "После сохранения:",
            "В кассе USD: 8 900",
        ]
    )
    await save(owner_client)
    assert await cash.cash_balance(session, USD) == Decimal("8900")


async def test_adjustment_cannot_make_cash_negative(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await adjust(session, owner_user, "100")
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_CASH)
    await owner_client.click(texts.BTN_ADJUST)
    await owner_client.click("USD")
    await owner_client.click(texts.BTN_REMOVE_MONEY)

    await owner_client.send("500")

    assert owner_client.last.text.endswith(
        "Недостаточно денег в кассе.\nВ кассе: 100 USD\nНужно: 500 USD\nВведите другую сумму:"
    )
    await owner_client.send("100")
    await owner_client.send("   ")
    assert owner_client.last.text == texts.REASON_EMPTY
    await owner_client.send("Личные расходы")
    await save(owner_client)
    assert await cash.cash_balance(session, USD) == 0


async def test_helper_has_no_adjustment(aigul: UserClient) -> None:
    await aigul.send("/menu")
    await aigul.click(texts.BTN_CASH)
    assert texts.BTN_ADJUST not in aigul.last.button_texts

    answer = await aigul.press(CashCb(action=CashAction.ADJUST).pack(), aigul.last)

    assert answer.text == texts.PERMISSION_DENIED


async def test_movements_list(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    timur = await make_client(session, owner_user, "Тимур")
    await adjust(session, owner_user, "10000")
    await record(session, owner_user, timur, OperationType.LEND, "1000")
    received = await record(session, owner_user, timur, OperationType.REPAY_IN, "1000")
    await adjust(session, owner_user, "-500", reason="Личные расходы")
    await reverse(session, owner_user, received, "ошибка")
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_CASH)

    await owner_client.click(texts.BTN_MOVEMENTS)

    day = format_short_date(TODAY)  # the service helpers date everything TODAY
    assert owner_client.last.button_texts[:5] == [
        f"№3 · {day} · Отмена №2 · Тимур · −1 000 USD",
        f"Корр. · {day} · −500 USD · Личные расходы",
        f"№2 · {day} · Мне вернули · Тимур · +1 000 USD · отменена",
        f"№1 · {day} · Выдал в долг · Тимур · −1 000 USD",
        f"Корр. · {day} · +10 000 USD · Остаток на начало работы",
    ]
    popup = await owner_client.click(f"Корр. · {day} · −500 USD · Личные расходы")
    assert popup is not None
    assert popup.startswith(
        f"Корректировка · {format_date(TODAY)}\n−500 USD\nПричина: Личные расходы"
    )
    await owner_client.click(f"№1 · {day} · Выдал в долг · Тимур · −1 000 USD")
    assert owner_client.last.text.startswith("Запись №1 · Выдал в долг")


# --- clients: scenario 10 and history ----------------------------------------------------------


async def test_scenario_10_counter_debts(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await adjust(session, owner_user, "10000")
    await new_debt(owner_client, texts.BTN_LEND, "Иван", "USD", "1000", new=True)
    await save(owner_client)
    await new_debt(owner_client, texts.BTN_BORROW, "Иван", "USD", "300")
    await save(owner_client)
    await new_debt(owner_client, texts.BTN_BORROW, "Иван", "RUB", "20000")
    await save(owner_client)

    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_CLIENTS)
    await owner_client.click("Иван")

    assert owner_client.last.text == "Иван\n\nДолги:\nUSD: должен вам 700\nRUB: вы должны 20 000"

    await owner_client.click(texts.BTN_HISTORY)
    day = today_text()[:5]
    assert owner_client.last.text == "История записей: Иван"
    assert owner_client.last.button_texts[:3] == [
        f"№3 · {day} · Взял в долг · 20 000 RUB",
        f"№2 · {day} · Взял в долг · 300 USD",
        f"№1 · {day} · Выдал в долг · 1 000 USD",
    ]
    await owner_client.click(f"№2 · {day} · Взял в долг · 300 USD")
    assert owner_client.last.text.startswith("Запись №2 · Взял в долг\nКлиент: Иван")
    await owner_client.click(texts.BTN_CLIENT)
    assert owner_client.last.text.startswith("Иван\n")


# --- record card -------------------------------------------------------------------------------


async def test_record_card(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await adjust(session, owner_user, "10000")
    await new_debt(
        owner_client, texts.BTN_LEND, "Азамат", "USD", "1000", new=True, comment="на ремонт"
    )
    await save(owner_client)

    await owner_client.click(texts.BTN_OPEN_RECORD)

    lines = owner_client.last.text.splitlines()
    assert lines[:5] == [
        "Запись №1 · Выдал в долг",
        "Клиент: Азамат",
        "Сумма: 1 000 USD",
        f"Дата: {today_text()}",
        "Комментарий: на ремонт",
    ]
    assert lines[5].startswith(f"Автор: Владелец · внесено {today_text()} ")
    assert len(lines) == 6
    assert owner_client.last.button_texts == [
        texts.BTN_CANCEL_RECORD,
        texts.BTN_CLIENT,
        texts.BTN_HOME,
    ]


async def test_record_card_other_currency(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    azamat = await make_client(session, owner_user, "Азамат")
    await adjust(session, owner_user, "1000")
    await record(session, owner_user, azamat, OperationType.LEND, "600")
    paid = await record(
        session,
        owner_user,
        azamat,
        OperationType.REPAY_IN,
        "52500",
        USD,
        pay_currency=KGS,
        rate="87.5",
    )
    await owner_client.send("/menu")

    await owner_client.press(
        RecordCb(action=RecordAction.OPEN, operation_id=paid.id).pack(), owner_client.last
    )

    assert owner_client.last.text.splitlines()[:5] == [
        f"Запись №{paid.id} · Мне вернули",
        "Клиент: Азамат",
        "Получено: 52 500 KGS",
        "Курс: 1 USD = 87,5 KGS",
        "Закрывает долг: 600 USD",
    ]


async def test_deleted_author_is_marked(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    helper = await users.add_helper(session, owner_user, "aigul_k")
    helper = await users.activate_by_username(session, HELPER_TG_ID, "aigul_k", "Айгуль")
    assert helper is not None
    timur = await make_client(session, owner_user, "Тимур")
    borrowed = await record(session, helper, timur, OperationType.BORROW, "100")
    await users.delete_helper(session, owner_user, helper.id)
    await owner_client.send("/menu")

    await owner_client.press(
        RecordCb(action=RecordAction.OPEN, operation_id=borrowed.id).pack(), owner_client.last
    )

    assert "Автор: Айгуль (удалён) · внесено" in owner_client.last.text
    assert texts.BTN_CANCEL_RECORD not in owner_client.last.button_texts


# --- scenario 12: a helper cancels her own mistake ---------------------------------------------


async def test_scenario_12(
    harness: Harness,
    owner_client: UserClient,
    aigul: UserClient,
    session: AsyncSession,
    owner_user: User,
) -> None:
    await adjust(session, owner_user, "10000")
    # The owner lends Тимур 1 000 USD.
    await new_debt(owner_client, texts.BTN_LEND, "Тимур", "USD", "1000", new=True)
    await save(owner_client)
    timur = await client_named(session, "Тимур")

    # Айгуль records «Мне вернули» 1 000 USD instead of 100.
    await repay_same(aigul, texts.BTN_REPAY_IN, "Тимур", "USD · должен 1 000", "1000")
    assert await save(aigul) == "Запись №2 сохранена."
    assert await balances.client_balance(session, timur.id, USD) == 0
    assert await cash.cash_balance(session, USD) == Decimal("10000")

    # The owner does not get a notice about a regular record of a helper (TZ 12.10)...
    owner_messages = len(owner_client.bot_messages)
    # ...and has no "Отменить запись" on Айгуль's record.
    await owner_client.send("/menu")
    await owner_client.press(
        RecordCb(action=RecordAction.OPEN, operation_id=2).pack(), owner_client.last
    )
    assert texts.BTN_CANCEL_RECORD not in owner_client.last.button_texts
    assert len(owner_client.bot_messages) == owner_messages + 1  # only the /menu answer
    refused = await owner_client.press(
        RecordCb(action=RecordAction.REVERSE, operation_id=2).pack(), owner_client.last
    )
    assert refused.text == texts.ONLY_AUTHOR_CAN_CANCEL

    # Айгуль cancels her record.
    await aigul.click(texts.BTN_OPEN_RECORD)
    await aigul.click(texts.BTN_CANCEL_RECORD)
    assert aigul.last.text == texts.ASK_CANCEL_REASON
    await aigul.send("ошибка в сумме, должно быть 100")
    assert aigul.last.text == "\n".join(
        [
            "Отменить запись №2?",
            "Мне вернули: Тимур",
            "Сумма: 1 000 USD",
            "Причина: ошибка в сумме, должно быть 100",
            "",
            "После отмены:",
            "Тимур должен вам: 1 000 USD",
            "В кассе USD: 9 000",
        ]
    )
    assert aigul.last.button_texts == [
        texts.BTN_CONFIRM_CANCEL,
        texts.BTN_BACK,
        texts.BTN_HOME,
    ]
    await aigul.click(texts.BTN_CONFIRM_CANCEL)

    result, menu = aigul.bot_messages[-2:]
    assert result.text == "Запись №2 отменена.\nТимур должен вам: 1 000 USD"
    assert menu.text == texts.MAIN_MENU
    assert await balances.client_balance(session, timur.id, USD) == Decimal("1000")
    assert await cash.cash_balance(session, USD) == Decimal("9000")

    notice = owner_client.bot_messages[-1]
    assert notice.text == "\n".join(
        [
            "Помощник отменил запись",
            "Кто: Айгуль (@aigul_k)",
            "Запись №2: Мне вернули · Тимур · 1 000 USD",
            "Причина: ошибка в сумме, должно быть 100",
        ]
    )
    await owner_client.click(texts.BTN_OPEN_RECORD, message=notice)
    assert "Статус: отменена записью №3 (причина: ошибка в сумме, должно быть 100)" in (
        owner_client.last.text
    )

    # A cancelled record cannot be cancelled again, and a reversal has no cancel button.
    await aigul.send("/menu")
    await aigul.press(RecordCb(action=RecordAction.OPEN, operation_id=2).pack(), aigul.last)
    assert texts.BTN_CANCEL_RECORD not in aigul.last.button_texts
    again = await aigul.press(
        RecordCb(action=RecordAction.REVERSE, operation_id=2).pack(), aigul.last
    )
    assert again.text == texts.ALREADY_REVERSED
    await aigul.press(RecordCb(action=RecordAction.OPEN, operation_id=3).pack(), aigul.last)
    assert aigul.last.text.splitlines()[0] == "Запись №3 · Отмена записи №2"
    assert f"Дата: {today_text()}" in aigul.last.text
    assert "Причина: ошибка в сумме, должно быть 100" in aigul.last.text
    assert texts.BTN_CANCEL_RECORD not in aigul.last.button_texts
    reversal_refused = await aigul.press(
        RecordCb(action=RecordAction.REVERSE, operation_id=3).pack(), aigul.last
    )
    assert reversal_refused.text == texts.CANNOT_REVERSE_REVERSAL

    # The correct record: Тимур owes 900 USD.
    await repay_same(aigul, texts.BTN_REPAY_IN, "Тимур", "USD · должен 1 000", "100")
    await save(aigul)
    assert await balances.client_balance(session, timur.id, USD) == Decimal("900")
    assert await count(session, Operation) == 4


async def test_owner_cancel_does_not_notify(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await adjust(session, owner_user, "100")
    await new_debt(owner_client, texts.BTN_LEND, "Тимур", "USD", "100", new=True)
    await save(owner_client)
    await owner_client.click(texts.BTN_OPEN_RECORD)
    await owner_client.click(texts.BTN_CANCEL_RECORD)
    await owner_client.send("ошибка")
    await owner_client.click(texts.BTN_CONFIRM_CANCEL)

    assert owner_client.bot_messages[-2].text == "Запись №1 отменена.\nТимур: долга в USD нет"
    assert owner_client.bot_messages[-1].text == texts.MAIN_MENU  # nothing after the menu
    assert await cash.cash_balance(session, USD) == Decimal("100")


async def test_cancel_needs_cash_for_received_money(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    timur = await make_client(session, owner_user, "Тимур")
    azamat = await make_client(session, owner_user, "Азамат")
    received = await record(session, owner_user, timur, OperationType.BORROW, "1000")
    await record(session, owner_user, azamat, OperationType.LEND, "1000")  # the cash is empty
    await owner_client.send("/menu")
    await owner_client.press(
        RecordCb(action=RecordAction.OPEN, operation_id=received.id).pack(), owner_client.last
    )

    popup = await owner_client.click(texts.BTN_CANCEL_RECORD)

    assert popup == "Недостаточно денег в кассе.\nВ кассе: 0 USD\nНужно: 1 000 USD"
    assert await count(session, Operation) == 2


async def test_cancel_reason_is_required_and_back_returns_to_card(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    timur = await make_client(session, owner_user, "Тимур")
    borrowed = await record(session, owner_user, timur, OperationType.BORROW, "100")
    await owner_client.send("/menu")
    await owner_client.press(
        RecordCb(action=RecordAction.OPEN, operation_id=borrowed.id).pack(), owner_client.last
    )
    await owner_client.click(texts.BTN_CANCEL_RECORD)

    await owner_client.send("  ")
    assert owner_client.last.text == texts.REASON_EMPTY
    await owner_client.send("я" * 501)
    assert "не больше 500 символов" in owner_client.last.text
    await owner_client.send("ошибка")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text == texts.ASK_CANCEL_REASON
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.startswith(f"Запись №{borrowed.id} · Взял в долг")
    assert await count(session, Operation) == 1


async def test_cash_adjustments_list_is_in_movements_only_once(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    for number in range(12):
        await adjust(session, owner_user, str(number + 1), reason=f"Причина {number}")
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_CASH)
    await owner_client.click(texts.BTN_MOVEMENTS)
    first_page = owner_client.last.button_texts[:10]
    await owner_client.click(texts.BTN_NEXT_PAGE)
    second_page = owner_client.last.button_texts[:2]

    assert len(set(first_page + second_page)) == 12
    assert await count(session, CashAdjustment) == 12
