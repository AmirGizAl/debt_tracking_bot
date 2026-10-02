"""«Балансы» and «Начальные балансы» through the bot (TZ 9, 13.7, 13.11; scenario 1)."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import OpeningAction, OpeningCb
from app.db.models import Operation, User
from app.services import ledger, opening
from tests.bot.harness import Harness, UserClient
from tests.conftest import create_user
from tests.services.accounting import (
    EUR,
    KGS,
    KZT,
    RUB,
    USD,
    D,
    cancel,
    force_close_day,
    open_balance,
)


async def save(client: UserClient) -> str:
    """Press «Сохранить»; returns the result message (the menu follows it)."""
    await client.click(texts.BTN_SAVE)
    result, menu = client.bot_messages[-2:]
    assert menu.text == texts.main_menu(1)
    return result.text


async def open_opening(client: UserClient) -> None:
    await client.send("/menu")
    await client.click(texts.BTN_SETTINGS)
    await client.click(texts.BTN_OPENING)


async def enter_opening(client: UserClient, currency: str, amount: str) -> None:
    await open_opening(client)
    await client.click(texts.BTN_ENTER)
    await client.click(currency)
    await client.send(amount)


async def test_balances_screen(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await open_balance(session, owner_user, "10000", USD)
    await open_balance(session, owner_user, "951000", KGS)
    await owner_client.send("/menu")

    await owner_client.click(texts.BTN_BALANCES)

    assert owner_client.last.text == (
        "Балансы · день №1\nUSD: 10 000\nEUR: 0\nRUB: 0\nKZT: 0\nНаличка: 951 000 KGS"
    )
    assert owner_client.last.button_texts == [
        texts.BTN_DAY_RECORDS,
        texts.BTN_ADJUST,
        texts.BTN_HOME,
    ]
    assert await owner_client.click(texts.BTN_ADJUST) == texts.SECTION_SOON


async def test_helper_sees_balances_without_adjustment(
    harness: Harness, session: AsyncSession
) -> None:
    await create_user(session, telegram_id=2002, username="aigul_k", full_name="Айгуль")
    helper = harness.user(2002, username="aigul_k")
    await helper.send("/menu")

    await helper.click(texts.BTN_BALANCES)

    assert helper.last.button_texts == [texts.BTN_DAY_RECORDS, texts.BTN_HOME]


async def test_scenario_1_opening_balances(owner_client: UserClient, session: AsyncSession) -> None:
    await open_opening(owner_client)
    assert owner_client.last.text.startswith(
        "Начальные балансы\nUSD: 0\nEUR: 0\nRUB: 0\nKZT: 0\nНаличка: 0 KGS\n\nВнесите деньги"
    )

    await owner_client.click(texts.BTN_ENTER)
    assert owner_client.last.button_texts[:5] == ["USD", "EUR", "RUB", "KZT", "KGS"]
    await owner_client.click("USD")
    await owner_client.send("10 000")
    assert owner_client.last.text == (
        "Проверьте начальный баланс\nВалюта: USD\nСумма: 10 000 USD\n\n"
        "После сохранения:\nБаланс USD: 10 000"
    )
    assert await save(owner_client) == "Запись №1 сохранена."
    await enter_opening(owner_client, "KGS", "1 000 000")
    assert owner_client.last.text.endswith("После сохранения:\nНаличка: 1 000 000 KGS")
    assert await save(owner_client) == "Запись №2 сохранена."

    assert await opening.baseline(session) == {
        USD: D("10000"),
        EUR: 0,
        RUB: 0,
        KZT: 0,
        KGS: D("1000000"),
    }
    await open_opening(owner_client)
    await owner_client.click(texts.BTN_ENTER)
    assert owner_client.last.button_texts[:3] == ["EUR", "RUB", "KZT"]  # USD and KGS are in


async def test_wrong_amount_is_asked_again(owner_client: UserClient) -> None:
    await enter_opening(owner_client, "USD", "десять")

    assert owner_client.last.text.endswith(texts.AMOUNT_ERRORS[texts.NumberProblem.FORMAT])
    await owner_client.send("10")
    assert owner_client.last.text.startswith("Проверьте начальный баланс")


async def test_second_opening_of_a_currency_is_refused(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    # The confirmation was open while the other owner entered USD.
    await enter_opening(owner_client, "USD", "10")
    await open_balance(session, owner_user, "20", USD)

    assert await save(owner_client) == f"{texts.opening_exists(USD)}\n{texts.RECORD_NOT_SAVED}"
    assert await session.scalar(select(func.count()).select_from(Operation)) == 1


async def test_after_the_first_closing_only_viewing(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await open_balance(session, owner_user, "10000", USD)
    await force_close_day(session, owner_user)

    await open_opening(owner_client)

    assert owner_client.last.text.endswith(texts.OPENING_FROZEN)
    assert texts.BTN_ENTER not in owner_client.last.button_texts


async def test_back_and_dont_save(owner_client: UserClient, session: AsyncSession) -> None:
    await enter_opening(owner_client, "USD", "10")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text == "Начальный баланс USD\nСколько USD на начало работы?"
    await owner_client.click(texts.BTN_BACK)
    assert texts.ASK_OPENING_CURRENCY in owner_client.last.text
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.startswith("Начальные балансы")

    await owner_client.click(texts.BTN_ENTER)
    await owner_client.click("USD")
    await owner_client.send("10")
    assert await owner_client.click(texts.BTN_DONT_SAVE) == texts.RECORD_NOT_SAVED
    assert owner_client.last.text == texts.main_menu(1)
    assert await ledger.balance(session, USD) == 0


async def test_helper_cannot_open_opening_balances(
    harness: Harness, session: AsyncSession, owner_user: User
) -> None:
    await create_user(session, telegram_id=2002, username="aigul_k", full_name="Айгуль")
    helper = harness.user(2002, username="aigul_k")
    await helper.send("/menu")

    answer = await helper.press(OpeningCb(action=OpeningAction.SHOW).pack(), helper.last)

    assert answer.text == texts.PERMISSION_DENIED


async def test_cancelled_opening_frees_the_currency(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    record = await open_balance(session, owner_user, "10", USD)
    await cancel(session, owner_user, record)

    await open_opening(owner_client)
    await owner_client.click(texts.BTN_ENTER)

    assert "USD" in owner_client.last.button_texts
