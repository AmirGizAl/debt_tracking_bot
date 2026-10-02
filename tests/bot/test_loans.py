"""«Долги в сомах» through the bot (TZ 13.5; scenarios 5 and the first part of 14)."""

from aiogram.fsm.storage.base import StorageKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.db.models import Operation, User
from app.domain.entries import Book, OperationType
from app.services import ledger, users
from tests.bot.harness import Harness, UserClient
from tests.bot.steps import records, save
from tests.factories import make_client
from tests.services.accounting import KGS, USD, D, loan, swap

BACK_ROW = [texts.BTN_BACK, texts.BTN_HOME]
SCREEN_BUTTONS = [
    [texts.BTN_LOAN_GIVE, texts.BTN_LOAN_REPAY_IN],
    [texts.BTN_LOAN_TAKE, texts.BTN_LOAN_REPAY_OUT],
    [texts.BTN_WHO_OWES],
    [texts.BTN_HOME],
]


async def start(client: UserClient, button: str, name: str | None = None) -> None:
    """«Долги в сомах» -> `button` -> the client from the recent ones."""
    await client.send("/menu")
    await client.click(texts.BTN_LOANS)
    await client.click(button)
    if name is not None:
        await client.click(name)


async def test_scenario_5_loan_to_bekzat(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    # Scenarios 2 and 3 left 1 001 000 KGS in the cash.
    await swap(session, funded, "1000", USD, "87000", KGS, rate="87")
    await swap(session, funded, "88000", KGS, "1000", USD, rate="88")

    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_LOANS)
    assert owner_client.last.text == "Долги в сомах\n\nВыберите действие:"
    assert owner_client.last.buttons == SCREEN_BUTTONS
    await owner_client.click(texts.BTN_LOAN_GIVE)
    assert owner_client.last.text == f"Выдал в долг\n\nКлиент?\n{texts.NO_CLIENTS_YET}"
    await owner_client.click(texts.BTN_NEW_CLIENT)
    await owner_client.send("Бекзат")
    await owner_client.click(texts.BTN_SKIP)
    assert owner_client.last.text == (
        "Выдал в долг: Бекзат\nНаличка: 1 001 000 KGS\n\nСколько сомов?"
    )
    assert owner_client.last.buttons == [BACK_ROW]
    await owner_client.send("50 000")
    assert owner_client.last.text == (
        "Выдал в долг: Бекзат\nСумма: 50 000 KGS\n\n"
        "Добавьте комментарий к записи или нажмите «Пропустить»:"
    )
    await owner_client.click(texts.BTN_SKIP)

    assert owner_client.last.text == "\n".join(
        [
            "Проверьте запись",
            "Выдал в долг: Бекзат",
            "Сумма: 50 000 KGS",
            "",
            "После сохранения:",
            "Бекзат: должен нам 50 000 KGS (долг в сомах)",
            "Наличка: 951 000 KGS",
        ]
    )
    assert owner_client.last.buttons == [[texts.BTN_SAVE, texts.BTN_DONT_SAVE], [texts.BTN_BACK]]
    assert await save(owner_client) == "Запись №5 сохранена."
    record = await session.scalar(select(Operation).where(Operation.id == 5))
    assert record is not None
    assert record.type == OperationType.LOAN_GIVE
    assert record.client_id is not None
    assert await ledger.balance(session, KGS) == D("951000")
    assert await ledger.client_obligations(session, record.client_id) == {
        (Book.LOAN, KGS): D("50000")
    }


async def test_scenario_14_helper_records_a_repayment(
    harness: Harness, session: AsyncSession, funded: User
) -> None:
    bekzat = await make_client(session, funded, "Бекзат")
    await loan(session, funded, OperationType.LOAN_GIVE, bekzat, "50000")
    await users.add_helper(session, funded, "aigul_k")
    aigul = harness.user(2002, username="aigul_k", first_name="Айгуль")
    await aigul.send("/start")

    await start(aigul, texts.BTN_LOAN_REPAY_IN, "Бекзат")
    assert aigul.last.text == (
        "Мне вернули: Бекзат\nБекзат: должен нам 50 000 KGS (долг в сомах)\n\nСколько сомов?"
    )
    assert aigul.last.buttons == [["Всю сумму: 50 000 KGS"], BACK_ROW]
    await aigul.send("5 000")  # the mistake of scenario 14: 5 000 instead of 50 000
    await aigul.click(texts.BTN_SKIP)

    assert aigul.last.text.endswith(
        "После сохранения:\nБекзат: должен нам 45 000 KGS (долг в сомах)\nНаличка: 955 000 KGS"
    )
    assert await save(aigul) == "Запись №4 сохранена."
    record = await session.scalar(select(Operation).where(Operation.id == 4))
    helper = await users.get_active_by_telegram_id(session, 2002)
    assert record is not None
    assert helper is not None
    assert (record.type, record.author_id) == (OperationType.LOAN_REPAY_IN, helper.id)


async def test_whole_debt_is_repaid_with_one_button(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    ivan = await make_client(session, funded, "Иван")
    await start(owner_client, texts.BTN_LOAN_TAKE, "Иван")
    assert owner_client.last.text == "Взял в долг: Иван\n\nСколько сомов?"  # the cash grows
    await owner_client.send("100 000")
    await owner_client.click(texts.BTN_SKIP)
    assert owner_client.last.text.endswith(
        "Иван: мы должны 100 000 KGS (долг в сомах)\nНаличка: 1 100 000 KGS"
    )
    await save(owner_client)

    await start(owner_client, texts.BTN_LOAN_REPAY_OUT, "Иван")
    assert owner_client.last.text == (
        "Я вернул: Иван\nИван: мы должны 100 000 KGS (долг в сомах)\n"
        "Наличка: 1 100 000 KGS\n\nСколько сомов?"
    )
    await owner_client.click("Всю сумму: 100 000 KGS")
    await owner_client.click(texts.BTN_SKIP)

    assert owner_client.last.text.endswith(
        "После сохранения:\nИван: долга в сомах нет\nНаличка: 1 000 000 KGS"
    )
    await save(owner_client)
    assert await ledger.client_obligations(session, ivan.id) == {}


async def test_warnings_of_repayments(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    bekzat = await make_client(session, funded, "Бекзат")
    await loan(session, funded, OperationType.LOAN_GIVE, bekzat, "40")

    await start(owner_client, texts.BTN_LOAN_REPAY_IN, "Бекзат")
    await owner_client.send("50")
    await owner_client.click(texts.BTN_SKIP)
    assert owner_client.last.text.endswith(
        "Бекзат: мы должны 10 KGS (долг в сомах)\nНаличка: 1 000 010 KGS\n\n"
        "Внимание: сумма больше долга клиента. Лишние 10 KGS станут нашим долгом перед ним."
    )

    await start(owner_client, texts.BTN_LOAN_REPAY_OUT, "Бекзат")
    assert owner_client.last.buttons == [BACK_ROW]  # we owe Бекзат nothing to repay
    await owner_client.send("5")
    await owner_client.click(texts.BTN_SKIP)
    assert owner_client.last.text.endswith(
        "Внимание: мы ничего не должны клиенту в KGS. Вся сумма станет долгом клиента перед нами."
    )


async def test_not_enough_cash_is_found_on_the_amount_step(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await make_client(session, funded, "Бекзат")
    await start(owner_client, texts.BTN_LOAN_GIVE, "Бекзат")

    await owner_client.send("2 000 000")

    assert owner_client.last.text == "\n\n".join(
        [
            "Выдал в долг: Бекзат\nНаличка: 1 000 000 KGS",
            "Недостаточно денег.\nНаличка: 1 000 000\nНужно: 2 000 000",
            "Сколько сомов?",
        ]
    )
    await owner_client.send("1 000 000")  # all the cash is fine
    assert owner_client.last.text.endswith("нажмите «Пропустить»:")


async def test_comment(owner_client: UserClient, session: AsyncSession, funded: User) -> None:
    await make_client(session, funded, "Бекзат")
    await start(owner_client, texts.BTN_LOAN_GIVE, "Бекзат")
    await owner_client.send("1000")

    await owner_client.send("x" * 501)
    assert texts.comment_too_long(500) in owner_client.last.text
    await owner_client.send("<i>до пятницы</i> & без процентов")

    assert "Комментарий: <i>до пятницы</i> & без процентов" in owner_client.last.text
    await save(owner_client)
    record = await session.scalar(select(Operation).order_by(Operation.id.desc()))
    assert record is not None
    assert record.comment == "<i>до пятницы</i> & без процентов"


async def test_back_from_every_step(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await make_client(session, funded, "Бекзат")
    await start(owner_client, texts.BTN_LOAN_GIVE, "Бекзат")
    await owner_client.send("1000")
    await owner_client.click(texts.BTN_SKIP)
    screens = []
    for _ in range(4):
        await owner_client.click(texts.BTN_BACK)
        screens.append(owner_client.last.text.splitlines()[-1])

    assert screens == [
        texts.ASK_RECORD_COMMENT,
        "Сколько сомов?",
        texts.CHOOSE_CLIENT_HINT,
        "Выберите действие:",
    ]
    assert owner_client.last.buttons == SCREEN_BUTTONS
    assert await records(session) == 2


async def test_dont_save(owner_client: UserClient, session: AsyncSession, funded: User) -> None:
    await make_client(session, funded, "Бекзат")
    await start(owner_client, texts.BTN_LOAN_GIVE, "Бекзат")
    await owner_client.send("1000")
    await owner_client.click(texts.BTN_SKIP)

    assert await owner_client.click(texts.BTN_DONT_SAVE) == texts.RECORD_NOT_SAVED
    assert owner_client.last.text == texts.main_menu(1)
    assert await records(session) == 2


async def test_who_owes_whom(owner_client: UserClient, session: AsyncSession, funded: User) -> None:
    for name, op_type, amount in (
        ("Азамат", OperationType.LOAN_GIVE, "20000"),
        ("Бекзат", OperationType.LOAN_GIVE, "50000"),
        ("Иван", OperationType.LOAN_TAKE, "100000"),
    ):
        client = await make_client(session, funded, name)
        await loan(session, funded, op_type, client, amount)
    tim = await make_client(session, funded, "Тимур")  # an exchange debt is not a som loan
    await swap(session, funded, "100", USD, "8700", KGS, rate="87", received_now=False, client=tim)

    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_LOANS)
    await owner_client.click(texts.BTN_WHO_OWES)

    assert owner_client.last.text == "\n".join(
        [
            "Долги в сомах · кто кому должен",
            "Итого нам должны: 70 000 KGS",
            "Итого мы должны: 100 000 KGS",
            "",
            "Нам должны:",
            "Бекзат — 50 000",
            "Азамат — 20 000",
            "",
            "Мы должны:",
            "Иван — 100 000",
        ]
    )
    assert owner_client.last.buttons == [BACK_ROW]
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.buttons == SCREEN_BUTTONS


async def test_who_owes_whom_pages(
    owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    for number in range(1, 12):
        client = await make_client(session, funded, f"Клиент {number:02}")
        await loan(session, funded, OperationType.LOAN_GIVE, client, str(number * 100))
    ivan = await make_client(session, funded, "Иван")
    await loan(session, funded, OperationType.LOAN_TAKE, ivan, "5")
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_LOANS)

    await owner_client.click(texts.BTN_WHO_OWES)
    first = owner_client.last.text.splitlines()
    assert first[:5] == [
        "Долги в сомах · кто кому должен",
        "Итого нам должны: 6 600 KGS",
        "Итого мы должны: 5 KGS",
        "",
        "Нам должны:",
    ]
    assert first[5:] == [f"Клиент {n:02} — {n * 100:,}".replace(",", " ") for n in range(11, 1, -1)]
    assert owner_client.last.buttons[0] == ["1/2", texts.BTN_NEXT_PAGE]

    await owner_client.click(texts.BTN_NEXT_PAGE)
    assert owner_client.last.text.splitlines()[3:] == [
        "",
        "Нам должны:",
        "Клиент 01 — 100",
        "",
        "Мы должны:",
        "Иван — 5",
    ]


async def test_nobody_owes_anything(owner_client: UserClient) -> None:
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_LOANS)

    await owner_client.click(texts.BTN_WHO_OWES)

    assert owner_client.last.text == "Долги в сомах · кто кому должен\nДолгов в сомах нет."


async def test_lost_scenario_data_leads_to_the_menu(
    harness: Harness, owner_client: UserClient, session: AsyncSession, funded: User
) -> None:
    await make_client(session, funded, "Бекзат")
    await start(owner_client, texts.BTN_LOAN_GIVE, "Бекзат")
    storage = harness.dispatcher.fsm.storage
    key = StorageKey(harness.bot.id, owner_client.chat_id, owner_client.chat_id)
    screen = (await storage.get_data(key))["screen_id"]
    await storage.set_data(key, {"screen_id": screen})  # the step is set, the form is gone

    await owner_client.send("1000")

    result, menu = owner_client.bot_messages[-2:]
    assert (result.text, menu.text) == (texts.STALE_ACTION, texts.main_menu(1))
    assert await records(session) == 2
