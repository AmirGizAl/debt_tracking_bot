"""«Начальные долги» through the bot (agreed with the customer on 03.10.2026)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import OpeningDebtAction, OpeningDebtCb
from app.db.models import User
from app.domain.entries import Book
from app.services import ledger, users
from tests.bot.harness import Harness, UserClient
from tests.bot.steps import records, save
from tests.factories import make_client
from tests.services.accounting import KGS, USD, D, force_close_day, open_balance

BACK_ROW = [texts.BTN_BACK, texts.BTN_HOME]


async def open_debts(client: UserClient) -> None:
    await client.send("/menu")
    await client.click(texts.BTN_SETTINGS)
    await client.click(texts.BTN_OPENING_DEBTS)


async def enter_debt(client: UserClient, name: str, currency: str) -> None:
    """Up to «Кто кому должен?» (for KGS the book is chosen by the caller)."""
    await open_debts(client)
    await client.click(texts.BTN_ENTER)
    await client.click(name)
    await client.click(currency)


async def test_we_owe_azamat_from_before_the_bot(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await open_balance(session, owner_user, "10000", USD)
    azamat = await make_client(session, owner_user, "Азамат")
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_SETTINGS)
    assert texts.BTN_OPENING_DEBTS in owner_client.last.button_texts
    await owner_client.click(texts.BTN_OPENING_DEBTS)
    assert owner_client.last.text == (
        f"Начальные долги\n{texts.OPENING_DEBTS_EMPTY}\n\n{texts.OPENING_DEBTS_HINT}"
    )
    await owner_client.click(texts.BTN_ENTER)
    assert owner_client.last.text.startswith("Начальный долг\n\nКлиент?")

    await owner_client.click("Азамат")
    assert owner_client.last.text == "Начальный долг\nКлиент: Азамат\n\nВ какой валюте долг?"
    await owner_client.click("USD")
    assert owner_client.last.text == (
        "Начальный долг\nКлиент: Азамат\nВалюта: USD\n\nКто кому должен?"
    )
    assert owner_client.last.buttons == [
        [texts.BTN_OWED_TO_US],
        [texts.BTN_WE_OWE],
        BACK_ROW,
    ]
    await owner_client.click(texts.BTN_WE_OWE)
    assert owner_client.last.text.endswith("Мы должны клиенту\n\nКакая сумма долга (USD)?")
    await owner_client.send("1 000")

    assert owner_client.last.text == "\n".join(
        [
            "Проверьте начальный долг",
            "Клиент: Азамат",
            "Долг: мы должны 1 000 USD",
            "Балансы не меняются.",
            "",
            "После сохранения:",
            "Азамат: мы должны 1 000 USD",
        ]
    )
    assert await save(owner_client) == "Запись №2 сохранена."
    assert await ledger.balance(session, USD) == D("10000")
    assert await ledger.client_obligations(session, azamat.id) == {(Book.EXCHANGE, USD): D("-1000")}
    await owner_client.click(texts.BTN_TO_PAY)
    assert owner_client.last.button_texts[0] == "Азамат · 1 000 USD"

    await open_debts(owner_client)
    assert owner_client.last.text.startswith("Начальные долги\nВсего: 1")
    await owner_client.click("Азамат · мы должны 1 000 USD")
    assert owner_client.last.text.splitlines()[:3] == [
        "Запись №2 · Начальный долг по обменам · день №1",
        "Клиент: Азамат",
        "Долг: мы должны 1 000 USD",
    ]


async def test_som_debt_asks_the_book(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    bekzat = await make_client(session, owner_user, "Бекзат")
    await enter_debt(owner_client, "Бекзат", "KGS")
    assert owner_client.last.text.endswith("Это долг в сомах или долг по обмену?")
    assert owner_client.last.buttons == [[texts.BTN_BOOK_LOAN, texts.BTN_BOOK_EXCHANGE], BACK_ROW]

    await owner_client.click(texts.BTN_BOOK_LOAN)
    await owner_client.click(texts.BTN_OWED_TO_US)
    await owner_client.send("50 000")

    assert owner_client.last.text.splitlines()[2] == "Долг: должен нам 50 000 KGS (долг в сомах)"
    assert owner_client.last.text.endswith("Бекзат: должен нам 50 000 KGS (долг в сомах)")
    await save(owner_client)
    assert await ledger.client_obligations(session, bekzat.id) == {(Book.LOAN, KGS): D("50000")}
    assert await ledger.balance(session, KGS) == 0
    await owner_client.click(texts.BTN_LOANS)
    await owner_client.click(texts.BTN_WHO_OWES)
    assert "Бекзат — 50 000" in owner_client.last.text


async def test_second_debt_of_the_client_in_a_currency_is_refused(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await make_client(session, owner_user, "Азамат")
    await enter_debt(owner_client, "Азамат", "USD")
    await owner_client.click(texts.BTN_OWED_TO_US)
    await owner_client.send("100")
    await save(owner_client)

    await enter_debt(owner_client, "Азамат", "USD")

    assert owner_client.last.text.endswith(
        "У клиента Азамат уже есть начальный долг в USD. Чтобы исправить его, отмените ту "
        "запись и внесите заново.\n\nВ какой валюте долг?"
    )
    await owner_client.click("KGS")
    await owner_client.click(texts.BTN_BOOK_EXCHANGE)  # another currency is fine
    assert owner_client.last.text.endswith("Кто кому должен?")


async def test_back_through_every_step(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await make_client(session, owner_user, "Бекзат")
    await enter_debt(owner_client, "Бекзат", "KGS")
    await owner_client.click(texts.BTN_BOOK_LOAN)
    await owner_client.click(texts.BTN_WE_OWE)
    await owner_client.send("100")
    screens = []
    for _ in range(6):
        await owner_client.click(texts.BTN_BACK)
        screens.append(owner_client.last.text.splitlines()[-1])

    assert screens == [
        "Какая сумма долга (KGS)?",
        texts.ASK_DEBT_DIRECTION,
        texts.ASK_DEBT_BOOK,
        texts.ASK_DEBT_CURRENCY,
        texts.CHOOSE_CLIENT_HINT,
        texts.OPENING_DEBTS_HINT,
    ]
    assert await records(session) == 0


async def test_helper_cannot_enter_opening_debts(
    harness: Harness, session: AsyncSession, owner_user: User
) -> None:
    await users.add_helper(session, owner_user, "aigul_k")
    aigul = harness.user(2002, username="aigul_k", first_name="Айгуль")
    await aigul.send("/start")

    for action in (OpeningDebtAction.SHOW, OpeningDebtAction.ENTER):
        answer = await aigul.press(OpeningDebtCb(action=action).pack(), aigul.last)
        assert answer.text == texts.PERMISSION_DENIED


async def test_cancelling_an_opening_debt_on_a_later_day(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    azamat = await make_client(session, owner_user, "Азамат")
    await enter_debt(owner_client, "Азамат", "USD")
    await owner_client.click(texts.BTN_OWED_TO_US)
    await owner_client.send("500")
    await save(owner_client)
    await force_close_day(session, owner_user)

    await open_debts(owner_client)
    await owner_client.click("Азамат · должен нам 500 USD")
    await owner_client.click(texts.BTN_CANCEL_RECORD)
    await owner_client.send("долг уже вернули")
    await owner_client.click(texts.BTN_CONFIRM_CANCEL)

    assert owner_client.bot_messages[-2].text == "Запись №1 отменена записью №2."
    assert await ledger.client_obligations(session, azamat.id) == {}
    await open_debts(owner_client)
    assert owner_client.last.text.startswith(f"Начальные долги\n{texts.OPENING_DEBTS_EMPTY}")


async def test_preliminary_report_counts_opening_debts_in_the_starting_point(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await open_balance(session, owner_user, "1000000", KGS)
    await make_client(session, owner_user, "Азамат")
    await enter_debt(owner_client, "Азамат", "USD")
    await owner_client.click(texts.BTN_OWED_TO_US)
    await owner_client.send("1 000")
    await save(owner_client)

    await owner_client.click(texts.BTN_REPORTS)
    await owner_client.click(texts.BTN_PRELIMINARY)
    assert owner_client.last.text.endswith("Сколько сомов за 1 USD?")  # the debt needs a rate
    await owner_client.send("87,65")

    lines = owner_client.last.text.splitlines()
    assert "Итог: 1 087 650" in lines
    assert "Начальная точка: 1 087 650" in lines
    assert "Излишки: 0" in lines
