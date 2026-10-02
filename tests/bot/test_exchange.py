"""«Обмен» through the bot UI (TZ 13.3; scenarios 2-4, 6, 10, 12, 13 of 17.1)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.db.models import Client, Operation, User
from app.domain.entries import Book, OperationType
from app.services import ledger
from tests.bot.harness import UserClient
from tests.bot.steps import records, save
from tests.factories import make_client
from tests.services.accounting import KGS, RUB, USD, D, loan, settle, swap

MENU = texts.main_menu(1)


async def deal(
    client: UserClient,
    give: str,
    amount: str,
    get: str,
    *,
    rate: str | None = None,
    second: str | None = None,
    enter_get: bool = False,
) -> None:
    """Up to the question «Как проходит обмен?»."""
    await client.send("/menu")
    await client.click(texts.BTN_EXCHANGE)
    await client.click(give)
    await client.click(get)
    if enter_get:
        await client.click(texts.BTN_ENTER_GET_AMOUNT)
    await client.send(amount)
    if rate is not None:
        await client.send(rate)
    if second is not None:
        await client.send(second)


async def test_scenario_2_instant_sale_of_dollars(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_EXCHANGE)
    assert owner_client.last.text == "Обмен\n\nЧто клиент отдаёт?"
    assert owner_client.last.button_texts[:5] == ["USD", "EUR", "RUB", "KZT", "KGS"]
    await owner_client.click("USD")
    await owner_client.click("KGS")
    assert owner_client.last.text == "Обмен\nUSD → KGS\n\nСколько клиент отдаёт (USD)?"
    await owner_client.send("1000")
    assert owner_client.last.text == "Обмен\n1 000 USD → KGS\n\nСколько сомов за 1 USD?"
    await owner_client.send("87")
    assert owner_client.last.text == (
        "Обмен\n1 000 USD → 87 000 KGS\nКурс: 1 USD = 87 KGS\n\nКак проходит обмен?"
    )
    await owner_client.click(texts.BTN_MODE_NOW)

    assert owner_client.last.text == "\n".join(
        [
            "Проверьте обмен",
            "Клиент: без имени",
            "Клиент отдаёт: 1 000 USD — получено",
            "Клиент получает: 87 000 KGS — выдано",
            "Курс: 1 USD = 87 KGS",
            "",
            "После сохранения:",
            "Баланс USD: 11 000",
            "Наличка: 913 000 KGS",
        ]
    )
    assert owner_client.last.buttons == [
        [texts.BTN_SAVE, texts.BTN_DONT_SAVE],
        [texts.BTN_EDIT_AMOUNT, texts.BTN_COMMENT],
        [texts.BTN_SET_CLIENT],
        [texts.BTN_BACK],
    ]
    assert await save(owner_client) == "Запись №3 сохранена."
    assert (await ledger.balance(session, USD), await ledger.balance(session, KGS)) == (
        D("11000"),
        D("913000"),
    )


async def test_scenario_3_instant_purchase_of_dollars(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await swap(session, funded, "1000", USD, "87000", KGS, rate="87")
    await deal(owner_client, "KGS", "88 000", "USD", rate="88")
    assert owner_client.last.text.startswith("Обмен\n88 000 KGS → 1 000 USD\nКурс: 1 USD = 88 KGS")

    await owner_client.click(texts.BTN_MODE_NOW)
    await save(owner_client)

    assert (await ledger.balance(session, USD), await ledger.balance(session, KGS)) == (
        D("10000"),
        D("1001000"),
    )


async def test_scenario_4_dollars_paid_later(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await deal(owner_client, "RUB", "88 500", "USD")
    assert owner_client.last.text.endswith("Сколько RUB за 1 USD?")
    await owner_client.send("88,5")
    await owner_client.click(texts.BTN_MODE_RECEIVED)
    assert owner_client.last.text.endswith(f"Клиент?\n{texts.NO_CLIENTS_YET}")
    await owner_client.click(texts.BTN_NEW_CLIENT)
    await owner_client.send("Азамат")
    await owner_client.click(texts.BTN_SKIP)

    assert owner_client.last.text == "\n".join(
        [
            "Проверьте обмен",
            "Клиент: Азамат",
            "Клиент отдаёт: 88 500 RUB — получено",
            "Клиент получает: 1 000 USD — выдадим позже",
            "Курс: 1 USD = 88,5 RUB",
            "",
            "После сохранения:",
            "Баланс RUB: 88 500",
            "Азамат: мы должны 1 000 USD",
        ]
    )
    assert texts.BTN_SET_CLIENT not in owner_client.last.button_texts
    await save(owner_client)
    azamat = await session.scalar(select(Client).where(Client.name == "Азамат"))
    assert azamat is not None
    assert await ledger.balance(session, RUB) == D("88500")
    assert await ledger.client_obligations(session, azamat.id) == {(Book.EXCHANGE, USD): D("-1000")}


async def test_scenario_6_not_enough_dollars(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await deal(owner_client, "KGS", "20 000", "USD", rate="88", enter_get=True)
    assert owner_client.last.text.startswith("Обмен\n1 760 000 KGS → 20 000 USD")

    await owner_client.click(texts.BTN_MODE_NOW)

    assert owner_client.last.text == "\n\n".join(
        [
            "Обмен\n1 760 000 KGS → 20 000 USD\nКурс: 1 USD = 88 KGS",
            "Недостаточно денег.\nБаланс USD: 10 000\nНужно: 20 000",
            "Как проходит обмен?",
        ]
    )
    assert await records(session) == 2  # only the opening balances
    # Paying out later needs no money now: it becomes our obligation.
    await owner_client.click(texts.BTN_MODE_RECEIVED)
    assert owner_client.last.text.endswith(f"Клиент?\n{texts.NO_CLIENTS_YET}")


async def test_scenario_10_purchase_of_currency_for_cash(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    # The state of day 2 before scenario 10 (scenarios 2-5 and 9): 9 000 USD, 951 000 KGS.
    azamat = await make_client(session, funded, "Азамат")
    bekzat = await make_client(session, funded, "Бекзат")
    await swap(session, funded, "1000", USD, "87000", KGS, rate="87")
    await swap(session, funded, "88000", KGS, "1000", USD, rate="88")
    await swap(
        session, funded, "88500", RUB, "1000", USD, rate="88.5", paid_now=False, client=azamat
    )
    await loan(session, funded, OperationType.LOAN_GIVE, bekzat, "50000")
    await settle(session, funded, OperationType.EXCHANGE_PAYOUT, azamat, "1000", USD)
    assert (await ledger.balance(session, USD), await ledger.balance(session, KGS)) == (
        D("9000"),
        D("951000"),
    )

    await deal(owner_client, "USD", "2 000", "KGS", rate="87,5")
    await owner_client.click(texts.BTN_MODE_NOW)

    assert owner_client.last.text.endswith("Баланс USD: 11 000\nНаличка: 776 000 KGS")
    await save(owner_client)
    assert (await ledger.balance(session, USD), await ledger.balance(session, KGS)) == (
        D("11000"),
        D("776000"),
    )


async def test_transfer_and_netting_scenarios_12_13(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    timur = await make_client(session, funded, "Тимур")
    # 12. A transfer without conversion: 100 000 RUB in now, 99 000 RUB out later.
    await deal(owner_client, "RUB", "100 000", "RUB", second="99 000")
    assert owner_client.last.text == (
        "Обмен\n100 000 RUB → 99 000 RUB\n\nКак проходит обмен?"
    )  # no rate for one currency
    await owner_client.click(texts.BTN_MODE_RECEIVED)
    await owner_client.click("Тимур")
    assert owner_client.last.text.endswith("Баланс RUB: 100 000\nТимур: мы должны 99 000 RUB")
    await save(owner_client)
    await owner_client.click(texts.BTN_TO_PAY)
    assert owner_client.last.button_texts[0] == "Тимур · 99 000 RUB"
    await owner_client.click(texts.BTN_HOME)
    await owner_client.click(texts.BTN_CLIENTS)
    await owner_client.click("Тимур")
    assert owner_client.last.text == "Тимур\n\nПо обменам:\nRUB: мы должны 99 000"

    # 13. Тимур takes som instead: his rubles "come later" and settle our debt.
    await deal(owner_client, "RUB", "99 000", "KGS", rate="0,99")
    await owner_client.click(texts.BTN_MODE_PAID)
    await owner_client.click("Тимур")
    assert owner_client.last.text.endswith("Наличка: 901 990 KGS\nТимур: обязательств в RUB нет")
    await save(owner_client)

    assert await ledger.client_obligations(session, timur.id) == {}
    assert await ledger.balance(session, KGS) == D("901990")
    await owner_client.click(texts.BTN_CLIENTS)
    await owner_client.click("Тимур")
    assert owner_client.last.text == "Тимур\n\nОбязательств нет"
    await owner_client.click(texts.BTN_HOME)
    await owner_client.click(texts.BTN_TO_PAY)
    assert owner_client.last.text == "Ждут выдачи\nСейчас никто не ждёт выдачи."


async def test_same_currency_same_amount_now_records_nothing(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await deal(owner_client, "USD", "100", "USD", second="100")

    await owner_client.click(texts.BTN_MODE_NOW)

    assert texts.NOTHING_TO_EXCHANGE in owner_client.last.text
    assert owner_client.last.text.endswith("Как проходит обмен?")


async def test_amount_the_client_gets_can_be_typed_instead(
    owner_client: UserClient, funded: User
) -> None:
    await deal(owner_client, "USD", "87 000", "KGS", rate="87", enter_get=True)

    assert owner_client.last.text.startswith("Обмен\n1 000 USD → 87 000 KGS")


async def test_last_rate_of_the_pair_today(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await swap(session, funded, "1000", USD, "87500", KGS, rate="87.5")
    await deal(owner_client, "KGS", "175 000", "USD")
    assert owner_client.last.button_texts[0] == "Последний курс: 87,5"

    await owner_client.click("Последний курс: 87,5")

    assert owner_client.last.text.startswith(
        "Обмен\n175 000 KGS → 2 000 USD\nКурс: 1 USD = 87,5 KGS"
    )


async def test_edit_amount_comment_and_client_on_confirmation(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await make_client(session, funded, "Азамат")
    await deal(owner_client, "USD", "1000", "KGS", rate="87,123")
    await owner_client.click(texts.BTN_MODE_NOW)
    assert "Клиент получает: 87 123 KGS — выдано" in owner_client.last.text

    await owner_client.click(texts.BTN_EDIT_AMOUNT)
    assert owner_client.last.text.endswith("Сколько клиент получает (KGS)? Введите новую сумму:")
    await owner_client.send("87 100")  # rounded to banknotes; the rate stays as entered
    await owner_client.click(texts.BTN_COMMENT)
    await owner_client.send("<b>купюры</b> & сдача")
    await owner_client.click(texts.BTN_SET_CLIENT)
    await owner_client.click("Азамат")

    text = owner_client.last.text
    assert "Клиент: Азамат" in text
    assert "Клиент получает: 87 100 KGS — выдано" in text
    assert "Курс: 1 USD = 87,123 KGS" in text
    assert "Комментарий: <b>купюры</b> & сдача" in text
    await save(owner_client)
    stored = await session.scalar(select(Operation).order_by(Operation.id.desc()))
    assert stored is not None
    assert (stored.get_amount, stored.rate, stored.comment) == (
        D("87100"),
        D("87.123"),
        "<b>купюры</b> & сдача",
    )
    assert stored.client_id is not None


async def test_back_goes_through_every_step(owner_client: UserClient, funded: User) -> None:
    await deal(owner_client, "RUB", "88 500", "USD", rate="88,5")
    await owner_client.click(texts.BTN_MODE_RECEIVED)
    screens = []
    for _ in range(5):
        await owner_client.click(texts.BTN_BACK)
        screens.append(owner_client.last.text.splitlines()[-1])

    assert screens == [
        "Как проходит обмен?",
        "Сколько RUB за 1 USD?",
        "Сколько клиент отдаёт (RUB)?",
        texts.ASK_GET_CURRENCY,
        texts.ASK_GIVE_CURRENCY,
    ]
    assert texts.BTN_BACK not in owner_client.last.button_texts  # the first step


async def test_wrong_inputs_keep_the_step(owner_client: UserClient, funded: User) -> None:
    await deal(owner_client, "USD", "абв", "KGS")
    assert owner_client.last.text.endswith(
        f"{texts.AMOUNT_ERRORS[texts.NumberProblem.FORMAT]}\n\nСколько клиент отдаёт (USD)?"
    )
    await owner_client.send("0,01")
    await owner_client.send("0,0001")  # 0.01 × 0.0001 rounds to 0 som
    assert texts.CONVERSION_ERRORS[texts.ConversionProblem.ZERO] in owner_client.last.text
    await owner_client.send("87,1234567")
    assert texts.RATE_ERRORS[texts.NumberProblem.PRECISION] in owner_client.last.text


async def test_double_tap_on_save_creates_one_record(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await deal(owner_client, "USD", "100", "KGS", rate="87")
    await owner_client.click(texts.BTN_MODE_NOW)
    confirmation = owner_client.last
    data = confirmation.callback_data(texts.BTN_SAVE)
    assert data is not None

    await owner_client.press(data, confirmation)
    second = await owner_client.press(data, confirmation)

    assert second.text == texts.STALE_ACTION
    assert await records(session) == 3


async def test_not_enough_money_at_save_time(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await deal(owner_client, "KGS", "870 000", "USD", rate="87")
    await owner_client.click(texts.BTN_MODE_NOW)
    # Somebody pays out dollars while the confirmation is open.
    await swap(session, funded, "870000", KGS, "10000", USD, rate="87")

    result = await save(owner_client)

    assert result == ("Недостаточно денег.\nБаланс USD: 0\nНужно: 10 000\nЗапись не сохранена.")


async def test_dont_save(owner_client: UserClient, session: AsyncSession, funded: User) -> None:
    await deal(owner_client, "USD", "100", "KGS", rate="87")
    await owner_client.click(texts.BTN_MODE_NOW)

    assert await owner_client.click(texts.BTN_DONT_SAVE) == texts.RECORD_NOT_SAVED
    assert owner_client.last.text == MENU
    assert await records(session) == 2


async def test_client_search_on_the_client_step(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    for name in ("Иван", "Иван (Ош)", "Бекзат"):
        await make_client(session, funded, name)
    await deal(owner_client, "RUB", "100", "USD", rate="90")
    await owner_client.click(texts.BTN_MODE_LATER)

    await owner_client.send("ИВ")  # typed text searches

    assert "Найдено по запросу «ИВ»: 2." in owner_client.last.text
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.endswith(texts.CHOOSE_CLIENT_HINT)
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.endswith("Как проходит обмен?")
