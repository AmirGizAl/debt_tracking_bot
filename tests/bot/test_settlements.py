"""«Ждут выдачи», «Ждут оплаты», payouts and receipts through the bot (TZ 13.4; scenario 9)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.db.models import Client, User
from app.domain.entries import Book, OperationType
from app.services import ledger
from tests.bot.harness import UserClient
from tests.bot.steps import records, save
from tests.factories import make_client
from tests.services.accounting import EUR, KGS, RUB, USD, D, open_balance, settle, swap

BACK_ROW = [texts.BTN_BACK, texts.BTN_HOME]
PAYOUT = OperationType.EXCHANGE_PAYOUT


async def we_owe(session: AsyncSession, owner: User, client: Client, usd: str) -> None:
    """An exchange of som for dollars that we pay out later."""
    som = str(D(usd) * 87)
    await swap(session, owner, som, KGS, usd, USD, rate="87", paid_now=False, client=client)


async def open_list(client: UserClient, button: str) -> None:
    await client.send("/menu")
    await client.click(button)


async def open_card(client: UserClient, name: str) -> None:
    await client.send("/menu")
    await client.click(texts.BTN_CLIENTS)
    await client.click(name)


async def test_scenario_9_azamat_gets_his_dollars(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    # Scenario 4 left us owing Азамат 1 000 USD.
    azamat = await make_client(session, funded, "Азамат")
    await swap(
        session, funded, "88500", RUB, "1000", USD, rate="88.5", paid_now=False, client=azamat
    )

    await open_list(owner_client, texts.BTN_TO_PAY)
    assert owner_client.last.text == (
        "Ждут выдачи\nИтого:\nUSD: 1 000\n\nНажмите на строку, чтобы выдать."
    )
    assert owner_client.last.buttons == [["Азамат · 1 000 USD"], [texts.BTN_HOME]]
    await owner_client.click("Азамат · 1 000 USD")
    assert owner_client.last.text == (
        "Выдача по обмену\nАзамат: мы должны 1 000 USD\nБаланс USD: 10 000\n\n"
        "Сколько выдаём клиенту Азамат (USD)?"
    )
    assert owner_client.last.buttons == [["Всю сумму: 1 000 USD"], BACK_ROW]
    await owner_client.click("Всю сумму: 1 000 USD")

    assert owner_client.last.text == "\n".join(
        [
            "Проверьте выдачу",
            "Клиент: Азамат",
            "Выдаём: 1 000 USD",
            "",
            "После сохранения:",
            "Баланс USD: 9 000",
            "Азамат: обязательств в USD нет",
        ]
    )
    assert owner_client.last.buttons == [[texts.BTN_SAVE, texts.BTN_DONT_SAVE], [texts.BTN_BACK]]
    assert await save(owner_client) == "Запись №4 сохранена."
    assert await ledger.balance(session, USD) == D("9000")
    assert await ledger.client_obligations(session, azamat.id) == {}
    await owner_client.click(texts.BTN_TO_PAY)
    assert owner_client.last.text == "Ждут выдачи\nСейчас никто не ждёт выдачи."


async def test_partial_receipt(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    ivan = await make_client(session, funded, "Иван")
    await swap(
        session, funded, "5000", RUB, "4950", KGS, rate="0.99", received_now=False, client=ivan
    )

    await open_list(owner_client, texts.BTN_TO_RECEIVE)
    assert owner_client.last.text == (
        "Ждут оплаты\nИтого:\nRUB: 5 000\n\nНажмите на строку, чтобы получить."
    )
    await owner_client.click("Иван · 5 000 RUB")
    assert owner_client.last.text == (
        "Получение по обмену\nИван: должен нам 5 000 RUB\n\nСколько получаем от клиента Иван (RUB)?"
    )
    await owner_client.send("3 000")

    assert owner_client.last.text == "\n".join(
        [
            "Проверьте получение",
            "Клиент: Иван",
            "Получаем: 3 000 RUB",
            "",
            "После сохранения:",
            "Баланс RUB: 3 000",
            "Иван: должен нам 2 000 RUB",
        ]
    )
    await save(owner_client)
    assert await ledger.client_obligations(session, ivan.id) == {(Book.EXCHANGE, RUB): D("2000")}
    await owner_client.click(texts.BTN_TO_RECEIVE)
    assert owner_client.last.button_texts[0] == "Иван · 2 000 RUB"


async def test_list_by_currency_with_totals_and_pages(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    for number in range(1, 12):
        client = await make_client(session, funded, f"Клиент {number:02}")
        await we_owe(session, funded, client, str(number * 10))
    timur = await make_client(session, funded, "Тимур")
    await swap(session, funded, "1000", RUB, "990", RUB, paid_now=False, client=timur)

    await open_list(owner_client, texts.BTN_TO_PAY)

    assert owner_client.last.text.startswith("Ждут выдачи\nИтого:\nUSD: 660\nRUB: 990\n")
    assert owner_client.last.button_texts[:3] == [
        "Клиент 11 · 110 USD",  # the largest first
        "Клиент 10 · 100 USD",
        "Клиент 09 · 90 USD",
    ]
    assert owner_client.last.buttons[-2:] == [["1/2", texts.BTN_NEXT_PAGE], [texts.BTN_HOME]]
    await owner_client.click(texts.BTN_NEXT_PAGE)
    assert owner_client.last.buttons[:2] == [["Клиент 01 · 10 USD"], ["Тимур · 990 RUB"]]

    await owner_client.click("Тимур · 990 RUB")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.buttons[:2] == [["Клиент 01 · 10 USD"], ["Тимур · 990 RUB"]]


async def test_payout_from_the_card_in_a_currency_we_owe_nothing(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    azamat = await make_client(session, funded, "Азамат")
    await we_owe(session, funded, azamat, "1000")
    await open_balance(session, funded, "500", EUR)

    await open_card(owner_client, "Азамат")
    assert owner_client.last.text == "Азамат\n\nПо обменам:\nUSD: мы должны 1 000"
    await owner_client.click(texts.BTN_GIVE_OUT)
    assert owner_client.last.text == "Выдача по обмену\nКлиент: Азамат\n\nВ какой валюте?"
    assert owner_client.last.buttons == [
        ["USD · мы должны 1 000"],
        ["EUR"],
        ["RUB"],
        ["KZT"],
        ["KGS"],
        BACK_ROW,
    ]
    await owner_client.click("EUR")
    assert owner_client.last.text == (
        "Выдача по обмену\nАзамат: обязательств в EUR нет\nБаланс EUR: 500\n\n"
        "Сколько выдаём клиенту Азамат (EUR)?"
    )
    assert owner_client.last.buttons == [BACK_ROW]  # no «Всю сумму»: we owe nothing in EUR
    await owner_client.send("200")

    assert owner_client.last.text.endswith(
        "Баланс EUR: 300\nАзамат: должен нам 200 EUR\n\n"
        "Внимание: мы ничего не должны клиенту в EUR. "
        "Вся сумма станет долгом клиента перед нами."
    )
    await save(owner_client)
    assert await ledger.client_obligations(session, azamat.id) == {
        (Book.EXCHANGE, USD): D("-1000"),
        (Book.EXCHANGE, EUR): D("200"),
    }


async def test_payout_of_more_than_we_owe(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    azamat = await make_client(session, funded, "Азамат")
    await we_owe(session, funded, azamat, "1000")
    await open_list(owner_client, texts.BTN_TO_PAY)
    await owner_client.click("Азамат · 1 000 USD")

    await owner_client.send("1 500")

    assert owner_client.last.text.endswith(
        "Баланс USD: 8 500\nАзамат: должен нам 500 USD\n\n"
        "Внимание: сумма больше нашего долга. Лишние 500 USD станут долгом клиента перед нами."
    )


async def test_receipt_from_the_card_when_the_client_owes_nothing(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await make_client(session, funded, "Иван")
    await open_card(owner_client, "Иван")
    assert owner_client.last.text == "Иван\n\nОбязательств нет"
    await owner_client.click(texts.BTN_TAKE_IN)
    assert owner_client.last.text == "Получение по обмену\nКлиент: Иван\n\nВ какой валюте?"
    await owner_client.click("RUB")
    await owner_client.send("100")

    assert owner_client.last.text.endswith(
        "Баланс RUB: 100\nИван: мы должны 100 RUB\n\n"
        "Внимание: клиент ничего не должен нам в RUB. Вся сумма станет нашим долгом перед ним."
    )


async def test_not_enough_money_is_found_on_the_amount_step(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    azamat = await make_client(session, funded, "Азамат")
    await we_owe(session, funded, azamat, "20000")
    await open_list(owner_client, texts.BTN_TO_PAY)
    await owner_client.click("Азамат · 20 000 USD")

    await owner_client.click("Всю сумму: 20 000 USD")

    assert owner_client.last.text == "\n\n".join(
        [
            "Выдача по обмену\nАзамат: мы должны 20 000 USD\nБаланс USD: 10 000",
            "Недостаточно денег.\nБаланс USD: 10 000\nНужно: 20 000",
            "Сколько выдаём клиенту Азамат (USD)?",
        ]
    )
    assert await records(session) == 3
    await owner_client.send("10 000")  # a part of the debt is fine
    assert owner_client.last.text.startswith("Проверьте выдачу")


async def test_not_enough_money_at_save_time(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    azamat = await make_client(session, funded, "Азамат")
    await we_owe(session, funded, azamat, "10000")
    await open_list(owner_client, texts.BTN_TO_PAY)
    await owner_client.click("Азамат · 10 000 USD")
    await owner_client.click("Всю сумму: 10 000 USD")
    # Somebody pays out dollars while the confirmation is open.
    await settle(session, funded, PAYOUT, azamat, "1", USD)

    result = await save(owner_client)

    assert result == "Недостаточно денег.\nБаланс USD: 9 999\nНужно: 10 000\nЗапись не сохранена."


async def test_whole_amount_after_somebody_settled_it(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    azamat = await make_client(session, funded, "Азамат")
    await we_owe(session, funded, azamat, "1000")
    await open_list(owner_client, texts.BTN_TO_PAY)
    await owner_client.click("Азамат · 1 000 USD")
    await settle(session, funded, PAYOUT, azamat, "1000", USD)

    popup = await owner_client.click("Всю сумму: 1 000 USD")

    assert popup == texts.STALE_ACTION
    assert owner_client.last.text.startswith("Выдача по обмену\nАзамат: обязательств в USD нет")
    assert owner_client.last.buttons == [BACK_ROW]


async def test_back_from_every_step(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    azamat = await make_client(session, funded, "Азамат")
    await we_owe(session, funded, azamat, "1000")
    # From a row of the list: confirmation -> amount -> the list.
    await open_list(owner_client, texts.BTN_TO_PAY)
    await owner_client.click("Азамат · 1 000 USD")
    await owner_client.send("100")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.endswith("Сколько выдаём клиенту Азамат (USD)?")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.startswith("Ждут выдачи\nИтого:")
    # From the card: amount -> currency -> the card.
    await open_card(owner_client, "Азамат")
    await owner_client.click(texts.BTN_GIVE_OUT)
    await owner_client.click("USD · мы должны 1 000")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.endswith("В какой валюте?")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text == "Азамат\n\nПо обменам:\nUSD: мы должны 1 000"
    assert await records(session) == 3


async def test_dont_save_and_double_tap(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    azamat = await make_client(session, funded, "Азамат")
    await we_owe(session, funded, azamat, "1000")
    await open_list(owner_client, texts.BTN_TO_PAY)
    await owner_client.click("Азамат · 1 000 USD")
    await owner_client.send("100")

    assert await owner_client.click(texts.BTN_DONT_SAVE) == texts.RECORD_NOT_SAVED
    assert owner_client.last.text == texts.main_menu(1)
    assert await records(session) == 3

    await owner_client.click(texts.BTN_TO_PAY)
    await owner_client.click("Азамат · 1 000 USD")
    await owner_client.send("100")
    confirmation = owner_client.last
    data = confirmation.callback_data(texts.BTN_SAVE)
    assert data is not None
    await owner_client.press(data, confirmation)
    second = await owner_client.press(data, confirmation)
    assert second.text == texts.STALE_ACTION
    assert await records(session) == 4
    assert await ledger.balance(session, USD) == D("9900")


async def test_an_older_list_starts_a_new_payout(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    azamat = await make_client(session, funded, "Азамат")
    await we_owe(session, funded, azamat, "1000")
    await open_list(owner_client, texts.BTN_TO_PAY)
    older_list = owner_client.last
    await open_list(owner_client, texts.BTN_TO_PAY)
    await owner_client.click("Азамат · 1 000 USD")
    await owner_client.send("100")
    await save(owner_client)

    # A list is a view: its rows keep working and start a fresh record.
    await owner_client.click("Азамат · 1 000 USD", message=older_list)
    assert owner_client.last.text.startswith("Выдача по обмену\nАзамат: мы должны 900 USD")
    await owner_client.send("900")
    await save(owner_client)
    assert await ledger.client_obligations(session, azamat.id) == {}
    assert await records(session) == 5
