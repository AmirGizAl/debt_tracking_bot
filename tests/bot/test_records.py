"""The record card, «Записи дня», the history of a client and the cancellation through the bot
(TZ 11, 13.6–13.8, 13.11; scenario 14)."""

from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import RecordAction, RecordCb
from app.db.models import Operation, User
from app.domain.dates import format_datetime
from app.domain.entries import OperationType
from app.services import ledger, users
from tests.bot.harness import Harness, UserClient
from tests.bot.steps import records, save
from tests.conftest import OWNER_TG_ID, SECOND_OWNER_TG_ID
from tests.factories import make_client
from tests.services.accounting import (
    KGS,
    RUB,
    USD,
    D,
    adjust,
    cancel,
    force_close_day,
    loan,
    open_balance,
    swap,
)

MOSCOW = ZoneInfo("Europe/Moscow")
LOAN_REPAY_IN = OperationType.LOAN_REPAY_IN


async def record(session: AsyncSession, record_id: int) -> Operation:
    found = await session.scalar(select(Operation).where(Operation.id == record_id))
    assert found is not None
    return found


def at(operation: Operation) -> str:
    return format_datetime(operation.created_at, MOSCOW)


async def open_record(client: UserClient, record_id: int) -> None:
    """«Открыть запись» from a notification or a result: a card without «Назад»."""
    data = RecordCb(action=RecordAction.OPEN, record_id=record_id).pack()
    await client.send("/menu")
    await client.press(data, client.last)


async def join_aigul(harness: Harness, session: AsyncSession, owner: User) -> UserClient:
    await users.add_helper(session, owner, "aigul_k")
    aigul = harness.user(2002, username="aigul_k", first_name="Айгуль")
    await aigul.send("/start")
    return aigul


# --- the card ------------------------------------------------------------------------------------


async def test_card_of_an_exchange(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await make_client(session, funded, "Азамат")
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_EXCHANGE)
    await owner_client.click("RUB")
    await owner_client.click("USD")
    await owner_client.send("88 500")
    await owner_client.send("88,5")
    await owner_client.click(texts.BTN_MODE_RECEIVED)
    await owner_client.click("Азамат")
    await owner_client.click(texts.BTN_COMMENT)
    await owner_client.send("<b>наличными</b>")
    assert await save(owner_client) == "Запись №3 сохранена."
    result = owner_client.bot_messages[-2]
    assert result.buttons == [[texts.BTN_OPEN_RECORD]]

    await owner_client.click(texts.BTN_OPEN_RECORD, message=result)

    assert owner_client.last.text == "\n".join(
        [
            "Запись №3 · Обмен · день №1",
            "Клиент: Азамат",
            "Клиент отдаёт: 88 500 RUB — получено",
            "Клиент получает: 1 000 USD — выдадим позже",
            "Курс: 1 USD = 88,5 RUB",
            "Комментарий: <b>наличными</b>",
            f"Автор: Владелец · {at(await record(session, 3))}",
        ]
    )
    assert owner_client.last.buttons == [
        [texts.BTN_CANCEL_RECORD],
        [texts.BTN_CLIENT],
        [texts.BTN_HOME],
    ]
    await owner_client.click(texts.BTN_CLIENT)
    assert owner_client.last.text.startswith("Азамат\n\nПо обменам:")


@pytest.mark.parametrize(
    ("make", "lines"),
    [
        ("instant", ["Клиент: без имени", "Клиент отдаёт: 1 000 USD — получено"]),
        ("loan", ["Клиент: Бекзат", "Сумма: 50 000 KGS"]),
        ("opening", ["Сумма: 10 000 USD"]),
        ("adjustment", ["Сумма: −500 USD", "Причина: пересчёт кассы"]),
    ],
)
async def test_card_of_every_kind_of_record(
    owner_client: UserClient,
    session: AsyncSession,
    funded: User,
    make: str,
    lines: list[str],
) -> None:
    bekzat = await make_client(session, funded, "Бекзат")
    if make == "instant":
        made = await swap(session, funded, "1000", USD, "87000", KGS, rate="87")
    elif make == "loan":
        made = await loan(session, funded, OperationType.LOAN_GIVE, bekzat, "50000")
    elif make == "opening":
        made = await record(session, 1)
    else:
        made = await adjust(session, funded, "-500", USD, "пересчёт кассы")

    await open_record(owner_client, made.id)

    text = owner_client.last.text.splitlines()
    assert text[1 : 1 + len(lines)] == lines
    assert text[-1] == f"Автор: Владелец · {at(made)}"
    # An adjustment is never cancelled (TZ 10): a counter-adjustment is made instead.
    assert (texts.BTN_CANCEL_RECORD in owner_client.last.button_texts) == (make != "adjustment")


async def test_cancelled_record_and_its_cancellation(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    bekzat = await make_client(session, funded, "Бекзат")
    given = await loan(session, funded, OperationType.LOAN_GIVE, bekzat, "50000")
    cancellation = await cancel(session, funded, given, "не тот клиент")

    await open_record(owner_client, given.id)
    assert owner_client.last.text.endswith(
        f"Статус: отменена записью №{cancellation.id} (причина: не тот клиент)"
    )
    assert texts.BTN_CANCEL_RECORD not in owner_client.last.button_texts

    await open_record(owner_client, cancellation.id)
    assert owner_client.last.text.splitlines()[0] == (
        f"Запись №{cancellation.id} · Выдал в долг · день №1"
    )
    assert owner_client.last.text.endswith(
        f"Статус: отмена записи №{given.id} (причина: не тот клиент)"
    )
    assert texts.BTN_CANCEL_RECORD not in owner_client.last.button_texts


# --- lists ---------------------------------------------------------------------------------------


async def test_records_of_the_day(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    azamat = await make_client(session, funded, "Азамат")
    await swap(session, funded, "1000", USD, "87000", KGS, rate="87")
    deal = await swap(
        session, funded, "88500", RUB, "1000", USD, rate="88.5", paid_now=False, client=azamat
    )
    await cancel(session, funded, deal, "ошибка")
    await adjust(session, funded, "-500", USD, "пересчёт")

    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_BALANCES)
    await owner_client.click(texts.BTN_DAY_RECORDS)

    assert owner_client.last.text == "Записи дня №1\nВсего: 6"
    assert owner_client.last.buttons == [
        ["№6 · Корректировка · −500 USD"],
        ["№5 · Обмен · Азамат · 88 500 RUB → 1 000 USD · отмена записи №4"],
        ["№4 · Обмен · Азамат · 88 500 RUB → 1 000 USD · отменена"],
        ["№3 · Обмен · без имени · 1 000 USD → 87 000 KGS"],
        ["№2 · Начальный баланс · 1 000 000 KGS"],
        ["№1 · Начальный баланс · 10 000 USD"],
        [texts.BTN_BACK, texts.BTN_HOME],
    ]
    await owner_client.click("№4 · Обмен · Азамат · 88 500 RUB → 1 000 USD · отменена")
    assert owner_client.last.buttons == [[texts.BTN_CLIENT], [texts.BTN_BACK, texts.BTN_HOME]]
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text == "Записи дня №1\nВсего: 6"
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.startswith("Балансы · день №1")


async def test_records_of_the_day_go_page_by_page_and_only_the_open_day(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await force_close_day(session, funded)
    for _ in range(12):
        await swap(session, funded, "1", USD, "87", KGS, rate="87")

    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_BALANCES)
    await owner_client.click(texts.BTN_DAY_RECORDS)

    assert owner_client.last.text == "Записи дня №2\nВсего: 12"
    assert owner_client.last.button_texts[0].startswith("№14 · ")
    await owner_client.click(texts.BTN_NEXT_PAGE)
    assert owner_client.last.button_texts[:2] == [
        "№4 · Обмен · без имени · 1 USD → 87 KGS",
        "№3 · Обмен · без имени · 1 USD → 87 KGS",
    ]
    await owner_client.click("№3 · Обмен · без имени · 1 USD → 87 KGS")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.buttons[-2] == [texts.BTN_PREV_PAGE, "2/2"]


async def test_empty_day(owner_client: UserClient) -> None:
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_BALANCES)

    await owner_client.click(texts.BTN_DAY_RECORDS)

    assert owner_client.last.text == f"Записи дня №1\n{texts.DAY_RECORDS_EMPTY}"


async def test_history_of_a_client(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    bekzat = await make_client(session, funded, "Бекзат")
    given = await loan(session, funded, OperationType.LOAN_GIVE, bekzat, "50000")
    await force_close_day(session, funded)
    await loan(session, funded, LOAN_REPAY_IN, bekzat, "5000")
    day = format_datetime(given.created_at, MOSCOW)[:5]
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_CLIENTS)
    await owner_client.click("Бекзат")

    await owner_client.click(texts.BTN_HISTORY)

    assert owner_client.last.text == "История записей: Бекзат\nВсего: 2"
    assert owner_client.last.button_texts[:2] == [
        f"№4 · {day} · Мне вернули · 5 000 KGS",
        f"№3 · {day} · Выдал в долг · 50 000 KGS",
    ]
    await owner_client.click(f"№3 · {day} · Выдал в долг · 50 000 KGS")
    assert owner_client.last.text.startswith("Запись №3 · Выдал в долг · день №1")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.startswith("История записей: Бекзат")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.startswith("Бекзат\n\nДолг в сомах: должен нам 45 000")


# --- cancellation --------------------------------------------------------------------------------


async def test_scenario_14_helper_fixes_a_wrong_repayment(
    harness: Harness, owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    # Day 3 before scenario 14: 677 990 KGS in the cash, Бекзат owes 50 000.
    await open_balance(session, owner_user, "727990", KGS)
    bekzat = await make_client(session, owner_user, "Бекзат")
    await loan(session, owner_user, OperationType.LOAN_GIVE, bekzat, "50000")
    aigul = await join_aigul(harness, session, owner_user)

    # Айгуль records 5 000 instead of 50 000 ...
    await aigul.click(texts.BTN_LOANS)
    await aigul.click(texts.BTN_LOAN_REPAY_IN)
    await aigul.click("Бекзат")
    await aigul.send("5 000")
    await aigul.click(texts.BTN_SKIP)
    assert await save(aigul) == "Запись №3 сохранена."
    await aigul.click(texts.BTN_OPEN_RECORD)
    assert aigul.last.buttons == [[texts.BTN_CANCEL_RECORD], [texts.BTN_CLIENT], [texts.BTN_HOME]]

    # ... cancels it with a reason ...
    await aigul.click(texts.BTN_CANCEL_RECORD)
    assert aigul.last.text == (
        "Отмена записи №3\nМне вернули · Бекзат · 5 000 KGS\n\nНапишите причину отмены:"
    )
    await aigul.send("   ")
    assert texts.REASON_EMPTY in aigul.last.text
    await aigul.send("ошибка в сумме")
    assert aigul.last.text == "\n".join(
        [
            "Отменить запись №3?",
            "Мне вернули · Бекзат · 5 000 KGS",
            "Причина: ошибка в сумме",
            "",
            "После отмены:",
            "Бекзат: должен нам 50 000 KGS (долг в сомах)",
            "Наличка: 677 990 KGS",
        ]
    )
    assert aigul.last.buttons == [[texts.BTN_CONFIRM_CANCEL], [texts.BTN_BACK]]
    await aigul.click(texts.BTN_CONFIRM_CANCEL)
    result, menu = aigul.bot_messages[-2:]
    assert (result.text, menu.text) == ("Запись №3 отменена записью №4.", texts.main_menu(1))
    assert result.buttons == [[texts.BTN_OPEN_RECORD]]

    # ... and records the right amount.
    await aigul.click(texts.BTN_LOANS)
    await aigul.click(texts.BTN_LOAN_REPAY_IN)
    await aigul.click("Бекзат")
    await aigul.click("Всю сумму: 50 000 KGS")
    await aigul.click(texts.BTN_SKIP)
    assert await save(aigul) == "Запись №5 сохранена."
    assert await ledger.client_obligations(session, bekzat.id) == {}
    assert await ledger.balance(session, KGS) == D("727990")

    # Both owners heard about the cancellation, with a button to the record.
    notice = (
        "Помощник отменил запись\nКто: Айгуль (@aigul_k)\n"
        "Запись №3: Мне вернули · Бекзат · 5 000 KGS\nПричина: ошибка в сумме"
    )
    for owner in (OWNER_TG_ID, SECOND_OWNER_TG_ID):
        received = [m for m in harness.chat(owner) if m.text == notice]
        assert len(received) == 1
        assert received[0].buttons == [[texts.BTN_OPEN_RECORD]]
    # The owner sees Айгуль's records without «Отменить запись».
    await owner_client.click(texts.BTN_OPEN_RECORD, message=harness.chat(OWNER_TG_ID)[-1])
    assert owner_client.last.text.endswith("Статус: отменена записью №4 (причина: ошибка в сумме)")
    assert texts.BTN_CANCEL_RECORD not in owner_client.last.button_texts
    await open_record(owner_client, 5)
    assert texts.BTN_CANCEL_RECORD not in owner_client.last.button_texts
    # Neither the cancelled record nor the cancellation can be cancelled.
    for record_id in (3, 4):
        await open_record(aigul, record_id)
        assert texts.BTN_CANCEL_RECORD not in aigul.last.button_texts


async def test_owner_cancelling_own_record_notifies_nobody(
    harness: Harness, owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    made = await swap(session, funded, "1000", USD, "87000", KGS, rate="87")
    await open_record(owner_client, made.id)
    await owner_client.click(texts.BTN_CANCEL_RECORD)
    await owner_client.send("дубль")

    await owner_client.click(texts.BTN_CONFIRM_CANCEL)

    assert owner_client.bot_messages[-2].text == f"Запись №{made.id} отменена записью №4."
    assert harness.chat(SECOND_OWNER_TG_ID) == []
    assert (await ledger.balance(session, USD), await ledger.balance(session, KGS)) == (
        D("10000"),
        D("1000000"),
    )


@pytest.mark.parametrize(
    ("case", "refusal"),
    [
        ("cancelled", texts.ALREADY_REVERSED),
        ("cancellation", texts.CANNOT_REVERSE_REVERSAL),
        ("adjustment", texts.CANNOT_REVERSE_ADJUSTMENT),
        ("someone_else", texts.ONLY_AUTHOR_CAN_CANCEL),
        ("frozen_opening", texts.OPENING_FROZEN),
    ],
)
async def test_hidden_cancel_button_refuses_when_pressed(
    harness: Harness,
    owner_client: UserClient,
    session: AsyncSession,
    funded: User,
    case: str,
    refusal: str,
) -> None:
    # An old card may still show the button: the rules are checked again on press (TZ 11.6).
    target = await swap(session, funded, "1000", USD, "87000", KGS, rate="87")
    if case == "cancelled":
        await cancel(session, funded, target)
    elif case == "cancellation":
        target = await cancel(session, funded, target)
    elif case == "adjustment":
        target = await adjust(session, funded, "100", USD)
    elif case == "someone_else":
        aigul = await join_aigul(harness, session, funded)
        helper = await users.get_active_by_telegram_id(session, aigul.chat_id)
        assert helper is not None
        target = await swap(session, helper, "100", USD, "8700", KGS, rate="87")
    else:
        target = await record(session, 1)
        await force_close_day(session, funded)
    data = RecordCb(action=RecordAction.CANCEL, record_id=target.id).pack()
    await owner_client.send("/menu")
    count = await records(session)

    answer = await owner_client.press(data, owner_client.last)

    assert answer.text == refusal
    assert answer.show_alert
    assert await records(session) == count


async def test_cancellation_that_needs_money_we_do_not_have(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    # The dollars of this exchange are already paid out to another client.
    came_in = await swap(session, funded, "1000", USD, "87000", KGS, rate="87")
    await swap(session, funded, "957000", KGS, "11000", USD, rate="87")
    await open_record(owner_client, came_in.id)

    popup = await owner_client.click(texts.BTN_CANCEL_RECORD)

    assert popup == "Недостаточно денег.\nБаланс USD: 0\nНужно: 1 000\nЗапись не отменена."
    assert owner_client.last.text.startswith(f"Запись №{came_in.id}")  # the card stays


async def test_back_from_the_cancellation(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await swap(session, funded, "1000", USD, "87000", KGS, rate="87")
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_BALANCES)
    await owner_client.click(texts.BTN_DAY_RECORDS)
    await owner_client.click("№3 · Обмен · без имени · 1 000 USD → 87 000 KGS")
    await owner_client.click(texts.BTN_CANCEL_RECORD)
    await owner_client.send("x" * 501)
    assert texts.comment_too_long(500) in owner_client.last.text
    await owner_client.send("дубль")

    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.endswith("Напишите причину отмены:")
    await owner_client.click(texts.BTN_BACK)

    assert owner_client.last.text.startswith("Запись №3 · Обмен")
    assert owner_client.last.buttons[-1] == [texts.BTN_BACK, texts.BTN_HOME]  # to the list
    assert await records(session) == 3


async def test_double_tap_on_cancel_cancels_once(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    made = await swap(session, funded, "1000", USD, "87000", KGS, rate="87")
    await open_record(owner_client, made.id)
    await owner_client.click(texts.BTN_CANCEL_RECORD)
    await owner_client.send("дубль")
    confirmation = owner_client.last
    data = confirmation.callback_data(texts.BTN_CONFIRM_CANCEL)
    assert data is not None

    await owner_client.press(data, confirmation)
    second = await owner_client.press(data, confirmation)

    assert second.text == texts.STALE_ACTION
    assert await records(session) == 4


async def test_cancelled_obligation_leaves_the_waiting_list(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    azamat = await make_client(session, funded, "Азамат")
    deal = await swap(
        session, funded, "88500", RUB, "1000", USD, rate="88.5", paid_now=False, client=azamat
    )
    await open_record(owner_client, deal.id)
    await owner_client.click(texts.BTN_CANCEL_RECORD)
    await owner_client.send("клиент передумал")
    assert owner_client.last.text.endswith(
        "После отмены:\nБаланс RUB: 0\nАзамат: обязательств в USD нет"
    )
    await owner_client.click(texts.BTN_CONFIRM_CANCEL)

    assert await ledger.client_obligations(session, azamat.id) == {}
    assert await ledger.balance(session, RUB) == 0
    await owner_client.click(texts.BTN_TO_PAY)
    assert owner_client.last.text == "Ждут выдачи\nСейчас никто не ждёт выдачи."
