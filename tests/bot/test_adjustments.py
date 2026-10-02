"""«Корректировка» through the bot (TZ 10, 13.7)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import BalancesAction, BalancesCb
from app.db.models import Operation, User
from app.domain.entries import OperationType
from app.services import ledger, users
from tests.bot.harness import Harness, UserClient
from tests.bot.steps import records, save
from tests.services.accounting import KGS, USD, D

BACK_ROW = [texts.BTN_BACK, texts.BTN_HOME]


async def start(client: UserClient) -> None:
    await client.send("/menu")
    await client.click(texts.BTN_BALANCES)
    await client.click(texts.BTN_ADJUST)


async def test_removing_money_after_a_count(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await start(owner_client)
    assert owner_client.last.text == "Корректировка\n\nКакой баланс исправить?"
    assert owner_client.last.buttons == [["USD", "EUR", "RUB", "KZT", "KGS"], BACK_ROW]
    await owner_client.click("USD")
    assert owner_client.last.text == (
        "Корректировка · USD\nБаланс USD: 10 000\n\nДобавить или убрать?"
    )
    assert owner_client.last.buttons == [[texts.BTN_ADJUST_ADD, texts.BTN_ADJUST_REMOVE], BACK_ROW]
    await owner_client.click(texts.BTN_ADJUST_REMOVE)
    assert owner_client.last.text == (
        "Корректировка · USD\nБаланс USD: 10 000\n\nСколько убрать (USD)?"
    )
    await owner_client.send("20 000")  # more than there is (TZ 10: no negative balance)
    assert "Недостаточно денег.\nБаланс USD: 10 000\nНужно: 20 000" in owner_client.last.text
    await owner_client.send("500")
    assert owner_client.last.text == (
        "Корректировка · USD\nИзменение: −500 USD\n\nНапишите причину корректировки:"
    )
    await owner_client.send(" ")
    assert texts.REASON_EMPTY in owner_client.last.text
    await owner_client.send("пересчёт кассы")

    assert owner_client.last.text == "\n".join(
        [
            "Проверьте корректировку",
            "Изменение: −500 USD",
            "Причина: пересчёт кассы",
            "",
            "После сохранения:",
            "Баланс USD: 9 500",
        ]
    )
    assert owner_client.last.buttons == [[texts.BTN_SAVE, texts.BTN_DONT_SAVE], [texts.BTN_BACK]]
    assert await save(owner_client) == "Запись №3 сохранена."
    assert owner_client.bot_messages[-2].buttons == [[texts.BTN_OPEN_RECORD]]
    stored = await session.scalar(select(Operation).where(Operation.id == 3))
    assert stored is not None
    assert (stored.type, stored.currency, stored.amount, stored.reason) == (
        OperationType.ADJUSTMENT,
        USD,
        D("-500"),
        "пересчёт кассы",
    )
    assert await ledger.balance(session, USD) == D("9500")


async def test_adding_money(owner_client: UserClient, session: AsyncSession, funded: User) -> None:
    await start(owner_client)
    await owner_client.click("KGS")
    await owner_client.click(texts.BTN_ADJUST_ADD)
    await owner_client.send("1 000,50")
    await owner_client.send("нашли в сейфе")

    assert owner_client.last.text.endswith(
        "Изменение: +1 000,50 KGS\nПричина: нашли в сейфе\n\n"
        "После сохранения:\nНаличка: 1 001 000,50 KGS"
    )
    await save(owner_client)
    assert await ledger.balance(session, KGS) == D("1001000.50")


async def test_back_through_every_step(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await start(owner_client)
    await owner_client.click("USD")
    await owner_client.click(texts.BTN_ADJUST_ADD)
    await owner_client.send("100")
    await owner_client.send("пересчёт")
    screens = []
    for _ in range(5):
        await owner_client.click(texts.BTN_BACK)
        screens.append(owner_client.last.text.splitlines()[-1])

    assert screens == [
        texts.ASK_ADJUST_REASON,
        "Сколько добавить (USD)?",
        texts.ASK_ADJUST_DIRECTION,
        texts.ASK_ADJUST_CURRENCY,
        "Наличка: 1 000 000 KGS",  # «Балансы»
    ]
    assert await records(session) == 2


async def test_dont_save(owner_client: UserClient, session: AsyncSession, funded: User) -> None:
    await start(owner_client)
    await owner_client.click("USD")
    await owner_client.click(texts.BTN_ADJUST_ADD)
    await owner_client.send("100")
    await owner_client.send("пересчёт")

    assert await owner_client.click(texts.BTN_DONT_SAVE) == texts.RECORD_NOT_SAVED
    assert await records(session) == 2


async def test_helper_cannot_adjust(harness: Harness, session: AsyncSession, funded: User) -> None:
    await users.add_helper(session, funded, "aigul_k")
    aigul = harness.user(2002, username="aigul_k", first_name="Айгуль")
    await aigul.send("/start")

    # The button is not shown to helpers; a forged press is refused anyway.
    answer = await aigul.press(BalancesCb(action=BalancesAction.ADJUST).pack(), aigul.last)

    assert answer.text == texts.PERMISSION_DENIED
    assert await records(session) == 2
