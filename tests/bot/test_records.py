"""Record scenarios in one currency through the bot UI (TZ 12.2-12.4, 15.1 scenarios 2-5, 8)."""

from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from aiogram.fsm.storage.base import StorageKey
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.handlers import operation_steps
from app.db.models import Client, Operation, User
from app.domain.currency import Currency
from app.domain.dates import today
from app.domain.operations import OperationType
from app.services import balances, cash, users
from tests.bot.harness import Harness, UserClient
from tests.bot.records import TZ, begin, fill_rest, new_debt, repay_same, save, today_text
from tests.factories import make_client
from tests.services.accounting import adjust, record

USD, RUB = Currency.USD, Currency.RUB


async def records_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Operation)) or 0


async def balance(session: AsyncSession, name: str, currency: Currency) -> Decimal:
    client = await session.scalar(select(Client).where(Client.name == name))
    assert client is not None
    return await balances.client_balance(session, client.id, currency)


@pytest.fixture
async def funded(session: AsyncSession, owner_user: User) -> User:
    """TZ 15.1 scenario 1 (done through the service here; the UI is tested with the cash)."""
    for amount, currency in (
        ("300000", Currency.KGS),
        ("10000", USD),
        ("2000", Currency.EUR),
        ("500000", RUB),
        ("1000000", Currency.KZT),
    ):
        await adjust(session, owner_user, amount, currency)
    return owner_user


async def test_scenarios_2_to_5(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    # 2. «Выдал в долг» Азамату 1 000 USD, a new client created on the way.
    await new_debt(
        owner_client, texts.BTN_LEND, "Азамат", "USD", "1000", new=True, comment="на ремонт машины"
    )
    assert owner_client.last.text == "\n".join(
        [
            "Проверьте запись",
            "Выдал в долг: Азамат",
            "Сумма: 1 000 USD",
            f"Дата: {today_text()}",
            "Комментарий: на ремонт машины",
            "",
            "Сейчас:",
            "Азамат: долга в USD нет",
            "",
            "После сохранения:",
            "Азамат должен вам: 1 000 USD",
            "В кассе USD: 9 000",
        ]
    )
    assert owner_client.last.buttons == [
        [texts.BTN_SAVE, texts.BTN_DONT_SAVE],
        [texts.BTN_BACK],
    ]
    assert await save(owner_client) == "Запись №1 сохранена."
    assert owner_client.bot_messages[-2].button_texts == [texts.BTN_OPEN_RECORD]
    assert await cash.cash_balance(session, USD) == Decimal("9000")

    # 3. «Мне вернули» от Азамата 400 USD.
    await begin(owner_client, texts.BTN_REPAY_IN, "Азамат")
    assert owner_client.last.text == (
        "Мне вернули: Азамат\n\nДолги:\nUSD: должен вам 1 000\n\nКакой долг закрывается?"
    )
    assert owner_client.last.button_texts[:5] == [
        "KGS",
        "USD · должен 1 000",
        "EUR",
        "RUB",
        "KZT",
    ]
    await owner_client.click("USD · должен 1 000")
    assert owner_client.last.button_texts[:2] == [
        texts.BTN_SAME_CURRENCY,
        texts.BTN_OTHER_CURRENCY,
    ]
    await owner_client.click(texts.BTN_SAME_CURRENCY)
    await fill_rest(owner_client, "400")
    assert owner_client.last.text == "\n".join(
        [
            "Проверьте запись",
            "Мне вернули: Азамат",
            "Сумма: 400 USD",
            f"Дата: {today_text()}",
            "",
            "Сейчас:",  # the debt the repayment closes (customer's request of 28.09.2026)
            "Азамат должен вам: 1 000 USD",
            "",
            "После сохранения:",
            "Азамат должен вам: 600 USD",
            "В кассе USD: 9 400",
        ]
    )
    assert await save(owner_client) == "Запись №2 сохранена."

    # 4. «Взял в долг» у Бекзата 50 000 RUB.
    await new_debt(owner_client, texts.BTN_BORROW, "Бекзат", "RUB", "50 000", new=True)
    assert "Бекзат: вы должны 50 000 RUB\nВ кассе RUB: 550 000" in owner_client.last.text
    assert await save(owner_client) == "Запись №3 сохранена."

    # 5. «Я вернул» Бекзату 20 000 RUB.
    await repay_same(owner_client, texts.BTN_REPAY_OUT, "Бекзат", "RUB · вы должны 50 000", "20000")
    assert "Сейчас:\nБекзат: вы должны 50 000 RUB\n" in owner_client.last.text
    assert "Бекзат: вы должны 30 000 RUB\nВ кассе RUB: 530 000" in owner_client.last.text
    assert await save(owner_client) == "Запись №4 сохранена."

    assert await balance(session, "Азамат", USD) == Decimal("600")
    assert await balance(session, "Бекзат", RUB) == Decimal("-30000")
    assert await cash.cash_balance(session, USD) == Decimal("9400")
    assert await cash.cash_balance(session, RUB) == Decimal("530000")


async def test_scenario_8_not_enough_cash_on_amount_step(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await adjust(session, owner_user, "9100")
    await make_client(session, owner_user, "Азамат")
    await begin(owner_client, texts.BTN_LEND, "Азамат")
    await owner_client.click("USD")
    assert "В кассе: 9 100 USD" in owner_client.last.text

    await owner_client.send("12 000")

    assert owner_client.last.text == (
        "Выдал в долг: Азамат\n\n"
        "Недостаточно денег в кассе.\nВ кассе: 9 100 USD\nНужно: 12 000 USD\nВведите другую сумму:"
    )
    assert await records_count(session) == 0
    await owner_client.send("9100")  # the whole cash is fine
    assert owner_client.last.text.endswith(texts.ASK_RECORD_COMMENT)


async def test_not_enough_cash_at_save_time(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    ivan = await make_client(session, owner_user, "Иван")
    await adjust(session, owner_user, "1000")
    await new_debt(owner_client, texts.BTN_LEND, "Иван", "USD", "800")
    # Somebody else spends the money while the confirmation screen is open.
    await record(session, owner_user, ivan, OperationType.LEND, "500")

    result = await save(owner_client)

    assert result == (
        "Недостаточно денег в кассе.\nВ кассе: 500 USD\nНужно: 800 USD\nЗапись не сохранена."
    )
    assert await records_count(session) == 1


@pytest.mark.parametrize(
    ("setup", "button", "debt_button", "amount", "warning"),
    [
        pytest.param(
            [(OperationType.LEND, "100")],
            texts.BTN_REPAY_IN,
            "USD · должен 100",
            "150",
            "Внимание: сумма больше долга. Лишние 50 USD станут вашим долгом перед клиентом.",
            id="repay_in-overpaid",
        ),
        pytest.param(
            [],
            texts.BTN_REPAY_IN,
            "USD",
            "10",
            "Внимание: клиент ничего не должен вам в USD. Вся сумма станет вашим долгом перед ним.",
            id="repay_in-nothing-owed",
        ),
        pytest.param(
            [],
            texts.BTN_REPAY_OUT,
            "USD",
            "10",
            "Внимание: вы ничего не должны клиенту в USD. "
            "Вся сумма станет долгом клиента перед вами.",
            id="repay_out-nothing-owed",
        ),
        pytest.param(
            [(OperationType.BORROW, "100")],
            texts.BTN_REPAY_OUT,
            "USD · вы должны 100",
            "130",
            "Внимание: сумма больше вашего долга. Лишние 30 USD станут долгом клиента перед вами.",
            id="repay_out-overpaid",
        ),
    ],
)
async def test_repay_warnings(
    owner_client: UserClient,
    session: AsyncSession,
    owner_user: User,
    setup: list[tuple[OperationType, str]],
    button: str,
    debt_button: str,
    amount: str,
    warning: str,
) -> None:
    nurlan = await make_client(session, owner_user, "Нурлан")
    await adjust(session, owner_user, "1000")
    for op_type, value in setup:
        await record(session, owner_user, nurlan, op_type, value)

    await repay_same(owner_client, button, "Нурлан", debt_button, amount)

    text = owner_client.last.text
    assert text.endswith(f"\n\n{warning}")
    assert f"<b>{warning}</b>" in owner_client.last.html


async def test_scenario_11_overpayment_saved(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await adjust(session, owner_user, "1000")
    await make_client(session, owner_user, "Нурлан")
    await new_debt(owner_client, texts.BTN_LEND, "Нурлан", "USD", "100")
    await save(owner_client)

    await repay_same(owner_client, texts.BTN_REPAY_IN, "Нурлан", "USD · должен 100", "150")
    assert "Лишние 50 USD" in owner_client.last.text
    await save(owner_client)

    assert await balance(session, "Нурлан", USD) == Decimal("-50")


async def test_back_goes_through_every_step(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await make_client(session, funded, "Азамат")
    await new_debt(owner_client, texts.BTN_LEND, "Азамат", "USD", "100")
    screens = []
    for _ in range(4):
        await owner_client.click(texts.BTN_BACK)
        screens.append(owner_client.last.text.splitlines()[-1])

    assert screens == [
        texts.ASK_RECORD_COMMENT,
        "Введите сумму в USD:",
        texts.ASK_CURRENCY,
        texts.CHOOSE_CLIENT_HINT,
    ]
    assert texts.BTN_BACK not in owner_client.last.button_texts  # the first step


async def test_dont_save(owner_client: UserClient, session: AsyncSession, funded: User) -> None:
    await make_client(session, funded, "Азамат")
    await new_debt(owner_client, texts.BTN_LEND, "Азамат", "USD", "100")

    popup = await owner_client.click(texts.BTN_DONT_SAVE)

    assert popup == texts.RECORD_NOT_SAVED
    assert owner_client.last.text == texts.MAIN_MENU
    assert await records_count(session) == 0


async def test_double_tap_on_save_creates_one_record(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await make_client(session, funded, "Азамат")
    await new_debt(owner_client, texts.BTN_LEND, "Азамат", "USD", "100")
    confirmation = owner_client.last
    data = confirmation.callback_data(texts.BTN_SAVE)
    assert data is not None

    await owner_client.press(data, confirmation)
    second = await owner_client.press(data, confirmation)  # arrives after the first finished

    assert second.text == texts.STALE_ACTION
    assert await records_count(session) == 1


async def test_old_confirmation_does_not_save_new_scenario(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    # Lesson from an earlier bot: "Сохранить" of an abandoned draft saved the newer data.
    await make_client(session, funded, "Азамат")
    await make_client(session, funded, "Бекзат")
    await new_debt(owner_client, texts.BTN_LEND, "Азамат", "USD", "100")
    old = owner_client.last
    old_save = old.callback_data(texts.BTN_SAVE)
    assert old_save is not None
    await new_debt(owner_client, texts.BTN_BORROW, "Бекзат", "RUB", "500")

    answer = await owner_client.press(old_save, old)

    assert answer.text == texts.STALE_ACTION
    assert await records_count(session) == 0
    assert await save(owner_client) == "Запись №1 сохранена."
    stored = await session.scalar(select(Operation))
    assert stored is not None
    assert (stored.type, stored.cash_amount) == (OperationType.BORROW, Decimal("500"))


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("abc", texts.AMOUNT_ERRORS[texts.NumberProblem.FORMAT]),
        ("0", texts.AMOUNT_ERRORS[texts.NumberProblem.NOT_POSITIVE]),
        ("10,555", texts.AMOUNT_ERRORS[texts.NumberProblem.PRECISION]),
    ],
)
async def test_wrong_amount_keeps_the_step(
    owner_client: UserClient, session: AsyncSession, funded: User, typed: str, expected: str
) -> None:
    await make_client(session, funded, "Азамат")
    await begin(owner_client, texts.BTN_BORROW, "Азамат")
    await owner_client.click("USD")

    await owner_client.send(typed)

    assert owner_client.last.text.endswith(expected)
    await owner_client.send("10")
    assert owner_client.last.text.endswith(texts.ASK_RECORD_COMMENT)


async def test_record_is_dated_today_without_asking(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    # The date step was removed at the customer's request (28.09.2026).
    await make_client(session, funded, "Азамат")
    await begin(owner_client, texts.BTN_BORROW, "Азамат")
    await owner_client.click("USD")

    await owner_client.send("10")

    assert owner_client.last.text == f"Взял в долг: Азамат · 10 USD\n\n{texts.ASK_RECORD_COMMENT}"
    assert owner_client.last.button_texts == [texts.BTN_SKIP, texts.BTN_BACK, texts.BTN_HOME]
    await owner_client.click(texts.BTN_SKIP)
    assert f"Дата: {today_text()}" in owner_client.last.text
    await save(owner_client)
    stored = await session.scalar(select(Operation))
    assert stored is not None
    assert stored.op_date == today(TZ)


async def test_record_date_is_taken_when_saving(
    owner_client: UserClient,
    session: AsyncSession,
    funded: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A confirmation left open over midnight saves the record with the new day.
    days = iter([date(2026, 9, 27), date(2026, 9, 28)])
    zones: list[ZoneInfo] = []

    def fake_today(zone: ZoneInfo) -> date:
        zones.append(zone)
        return next(days)

    monkeypatch.setattr(operation_steps, "today", fake_today)
    await make_client(session, funded, "Азамат")
    await new_debt(owner_client, texts.BTN_BORROW, "Азамат", "USD", "10")
    assert "Дата: 27.09.2026" in owner_client.last.text

    await save(owner_client)

    stored = await session.scalar(select(Operation))
    assert stored is not None
    assert stored.op_date == date(2026, 9, 28)
    assert zones == [TZ, TZ]  # Moscow time


async def test_search_on_client_step(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    for number in range(8):
        await make_client(session, funded, f"Клиент {number}")
    await make_client(session, funded, "Азамат Ош")
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_LEND)

    await owner_client.send("аза")  # typed text searches (TZ 12.2)

    assert owner_client.last.text.startswith("Найдено по запросу «аза»: 1.")
    await owner_client.click("Азамат Ош")
    assert owner_client.last.text == f"Выдал в долг: Азамат Ош\n\n{texts.ASK_CURRENCY}"


async def test_comment_is_escaped_and_limited(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await make_client(session, funded, "<Иван & Ко>")
    await begin(owner_client, texts.BTN_BORROW, "<Иван & Ко>")
    await owner_client.click("USD")
    await owner_client.send("10")

    await owner_client.send("я" * 501)
    assert "не больше 500 символов" in owner_client.last.text
    await owner_client.send("<b>не жирный</b> & точка")

    assert "Комментарий: <b>не жирный</b> & точка" in owner_client.last.text
    assert "<Иван & Ко>: вы должны 10 USD" in owner_client.last.text


async def test_deleting_helper_drops_their_scenario(
    harness: Harness, owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await users.add_helper(session, funded, "aigul_k")
    helper = harness.user(2002, username="aigul_k", first_name="Айгуль")
    await helper.send("/start")
    await make_client(session, funded, "Азамат")
    await begin(helper, texts.BTN_BORROW, "Азамат")
    key = StorageKey(bot_id=harness.bot.id, chat_id=2002, user_id=2002)
    assert await harness.dispatcher.fsm.storage.get_state(key) is not None

    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_SETTINGS)
    await owner_client.click(texts.BTN_HELPERS)
    await owner_client.click("Айгуль (@aigul_k) · активен")
    await owner_client.click(texts.BTN_DELETE)
    await owner_client.click(texts.BTN_CONFIRM_DELETE)

    assert await harness.dispatcher.fsm.storage.get_state(key) is None
    assert await harness.dispatcher.fsm.storage.get_data(key) == {}
    await helper.send("USD")
    assert helper.last.text == texts.NO_ACCESS
