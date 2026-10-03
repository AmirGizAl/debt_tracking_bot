"""TZ 17.1: every acceptance scenario one after another on a clean database, through the bot.

Two owners (OWNER_TG_ID, SECOND_OWNER_TG_ID) and the helper Айгуль. Every step goes through the
real dispatcher and the fake Telegram, the numbers are read from the screens of the bot.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.db.models import Operation, User
from tests.bot.harness import FakeMessage, Harness, UserClient
from tests.conftest import OWNER_TG_ID, SECOND_OWNER_TG_ID


async def records(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Operation)) or 0


async def menu(client: UserClient) -> None:
    await client.send("/menu")


async def balances(client: UserClient) -> list[str]:
    await menu(client)
    await client.click(texts.BTN_BALANCES)
    return client.last.text.splitlines()[1:]


async def save(client: UserClient, day: int) -> str:
    await client.click(texts.BTN_SAVE)
    result, main_menu = client.bot_messages[-2:]
    assert main_menu.text == texts.main_menu(day)
    return result.text


async def exchange(
    client: UserClient,
    give: str,
    get: str,
    amount: str,
    *,
    rate: str | None = None,
    second: str | None = None,
    enter_get: bool = False,
) -> None:
    """«Обмен» up to «Как проходит обмен?»."""
    await menu(client)
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


async def card_of(client: UserClient, name: str) -> str:
    await menu(client)
    await client.click(texts.BTN_CLIENTS)
    await client.click(name)
    return client.last.text


async def preliminary(client: UserClient, *rates: str) -> list[str]:
    await menu(client)
    await client.click(texts.BTN_REPORTS)
    await client.click(texts.BTN_PRELIMINARY)
    for rate in rates:
        await client.send(rate)
    return client.last.text.splitlines()


async def close_day(client: UserClient, day: int, *rates: str) -> list[str]:
    """Up to the check screen; returns its lines, then closes the day."""
    await menu(client)
    await client.click(texts.BTN_CLOSE_DAY)
    for rate in rates:
        await client.send(rate)
    check = client.last.text.splitlines()
    assert check[0] == f"День №{day} — проверка перед закрытием"
    await client.click(f"Закрыть день №{day}")
    return check


def documents(messages: list[FakeMessage]) -> list[str]:
    return [m.document_name for m in messages if m.document_name is not None]


async def test_acceptance_scenarios(
    harness: Harness, owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    owner = owner_client
    # The helper Айгуль joins: added by nickname, then opens the bot.
    await menu(owner)
    await owner.click(texts.BTN_SETTINGS)
    await owner.click(texts.BTN_HELPERS)
    await owner.click(texts.BTN_ADD)
    await owner.send("@aigul_k")
    aigul = harness.user(2002, username="aigul_k", first_name="Айгуль")
    await aigul.send("/start")
    assert aigul.last.text == texts.main_menu(1)

    # --- Day №1 ------------------------------------------------------------------------------

    # 1. Opening balances; the preliminary report shows no surplus.
    for currency, amount in (("USD", "10 000"), ("KGS", "1 000 000")):
        await menu(owner)
        await owner.click(texts.BTN_SETTINGS)
        await owner.click(texts.BTN_OPENING)
        await owner.click(texts.BTN_ENTER)
        await owner.click(currency)
        await owner.send(amount)
        await save(owner, 1)
    report = await preliminary(owner, "87,65")
    assert report[1:] == [
        "USD: 10 000 + 0 − 0 = 10 000 × 87,65 = 876 500",
        "Наличка: 1 000 000",
        "Долги в сомах: нам 0, мы 0",
        "",
        "Итог: 1 876 500",
        "Начальная точка: 1 876 500",
        "Излишки: 0",
        "Изменение за день: 0",
        "",
        texts.CHOOSE_FORMAT,
    ]

    # 2. An instant exchange without a name: 1 000 USD for som at 87.
    await exchange(owner, "USD", "KGS", "1000", rate="87")
    assert owner.last.text.startswith("Обмен\n1 000 USD → 87 000 KGS")
    await owner.click(texts.BTN_MODE_NOW)
    await save(owner, 1)
    assert await balances(owner) == [
        "USD: 11 000",
        "EUR: 0",
        "RUB: 0",
        "KZT: 0",
        "Наличка: 913 000 KGS",
    ]

    # 3. 88 000 KGS for dollars at 88.
    await exchange(owner, "KGS", "USD", "88 000", rate="88")
    assert owner.last.text.startswith("Обмен\n88 000 KGS → 1 000 USD")
    await owner.click(texts.BTN_MODE_NOW)
    await save(owner, 1)
    lines = await balances(owner)
    assert (lines[0], lines[-1]) == ("USD: 10 000", "Наличка: 1 001 000 KGS")

    # 4. Азамат gives 88 500 RUB, gets 1 000 USD later.
    await exchange(owner, "RUB", "USD", "88 500")
    assert owner.last.text.endswith("Сколько RUB за 1 USD?")
    await owner.send("88,5")
    await owner.click(texts.BTN_MODE_RECEIVED)
    await owner.click(texts.BTN_NEW_CLIENT)
    await owner.send("Азамат")
    await owner.click(texts.BTN_SKIP)
    assert owner.last.text.endswith("Баланс RUB: 88 500\nАзамат: мы должны 1 000 USD")
    await save(owner, 1)
    assert (await balances(owner))[2] == "RUB: 88 500"
    await menu(owner)
    await owner.click(texts.BTN_TO_PAY)
    assert owner.last.button_texts[0] == "Азамат · 1 000 USD"

    # 5. A som loan to Бекзат.
    await menu(owner)
    await owner.click(texts.BTN_LOANS)
    await owner.click(texts.BTN_LOAN_GIVE)
    await owner.click(texts.BTN_NEW_CLIENT)
    await owner.send("Бекзат")
    await owner.click(texts.BTN_SKIP)
    await owner.send("50 000")
    await owner.click(texts.BTN_SKIP)
    assert owner.last.text.endswith(
        "Бекзат: должен нам 50 000 KGS (долг в сомах)\nНаличка: 951 000 KGS"
    )
    await save(owner, 1)
    assert (await balances(owner))[-1] == "Наличка: 951 000 KGS"
    assert (await card_of(owner, "Бекзат")).endswith("Долг в сомах: должен нам 50 000")

    # 6. Paying out 20 000 USD now is refused, nothing is recorded.
    saved = await records(session)
    await exchange(owner, "KGS", "USD", "20 000", rate="88", enter_get=True)
    await owner.click(texts.BTN_MODE_NOW)
    assert "Недостаточно денег.\nБаланс USD: 10 000\nНужно: 20 000" in owner.last.text
    assert await records(session) == saved

    # 7. The preliminary report of the control example 8.6.
    report = await preliminary(owner, "87,65", "0,991")
    assert report[1:10] == [
        "USD: 10 000 + 0 − 1 000 = 9 000 × 87,65 = 788 850",
        "RUB: 88 500 + 0 − 0 = 88 500 × 0,991 = 87 703,50",
        "Наличка: 951 000",
        "Долги в сомах: нам 50 000, мы 0",
        "",
        "Итог: 1 877 553,50",
        "Начальная точка: 1 876 500",
        "Излишки: +1 053,50",
        "Изменение за день: +1 053,50",
    ]

    # 8. The helper cannot close the day; the owner closes it, both owners get the files.
    await menu(aigul)
    assert texts.BTN_CLOSE_DAY not in aigul.last.button_texts
    assert all(texts.BTN_CLOSE_DAY not in row for row in aigul.panel)
    check = await close_day(owner, 1, "87,65", "0,991")
    assert check[-1] == "Изменение за день: +1 053,50"
    assert "День №1 закрыт. Излишки: +1 053,50 сома. Начат день №2." in [
        m.text for m in owner.bot_messages
    ]
    for chat in (OWNER_TG_ID, SECOND_OWNER_TG_ID):
        names = documents(harness.chat(chat))
        assert [name.rsplit(".", 1)[1] for name in names] == ["xlsx", "pdf"]
        assert all(name.startswith("Отчёт_дня_1_") for name in names)
    assert owner.bot_messages[-1].text == texts.main_menu(2)

    # --- Day №2 ------------------------------------------------------------------------------

    # 9. Азамат gets his 1 000 USD.
    await menu(owner)
    await owner.click(texts.BTN_TO_PAY)
    await owner.click("Азамат · 1 000 USD")
    await owner.click("Всю сумму: 1 000 USD")
    await save(owner, 2)
    assert (await balances(owner))[0] == "USD: 9 000"
    assert (await card_of(owner, "Азамат")).endswith("Обязательств нет")
    await menu(owner)
    await owner.click(texts.BTN_TO_PAY)
    assert owner.last.text == "Ждут выдачи\nСейчас никто не ждёт выдачи."

    # 10. 2 000 USD bought for som at 87,5.
    await exchange(owner, "USD", "KGS", "2 000", rate="87,5")
    await owner.click(texts.BTN_MODE_NOW)
    await save(owner, 2)
    lines = await balances(owner)
    assert (lines[0], lines[-1]) == ("USD: 11 000", "Наличка: 776 000 KGS")

    # 11. Closing of day 2; the archive keeps day 1 as it was.
    check = await close_day(owner, 2, "87,70", "0,99")
    assert check[-4:] == [
        "Итог: 1 878 315",
        "Начальная точка: 1 877 000",
        "Излишки: +1 315",
        "Изменение за день: +261,50",
    ]
    await menu(owner)
    await owner.click(texts.BTN_REPORTS)
    await owner.click(texts.BTN_ARCHIVE)
    day_2, day_1 = owner.last.buttons[0][0], owner.last.buttons[1][0]
    assert day_2.startswith("День №2 · ")
    assert day_2.endswith(" · +1 315")
    assert day_1.endswith(" · +1 053,50")
    await owner.click(day_1)
    assert "Излишки: +1 053,50" in owner.last.text

    # --- Day №3 ------------------------------------------------------------------------------

    # 12. A transfer without conversion with Тимур.
    await exchange(owner, "RUB", "RUB", "100 000", second="99 000")
    await owner.click(texts.BTN_MODE_RECEIVED)
    await owner.click(texts.BTN_NEW_CLIENT)
    await owner.send("Тимур")
    await owner.click(texts.BTN_SKIP)
    assert owner.last.text.endswith("Баланс RUB: 188 500\nТимур: мы должны 99 000 RUB")
    await save(owner, 3)
    assert (await balances(owner))[2] == "RUB: 188 500"

    # 13. Netting: Тимур takes som for his rubles.
    await exchange(owner, "RUB", "KGS", "99 000", rate="0,99")
    await owner.click(texts.BTN_MODE_PAID)
    await owner.click("Тимур")
    await save(owner, 3)
    assert (await card_of(owner, "Тимур")).endswith("Обязательств нет")
    assert (await balances(owner))[-1] == "Наличка: 677 990 KGS"

    # 14. Айгуль records 5 000 instead of 50 000, cancels it and records the right amount.
    await menu(aigul)
    await aigul.click(texts.BTN_LOANS)
    await aigul.click(texts.BTN_LOAN_REPAY_IN)
    await aigul.click("Бекзат")
    await aigul.send("5 000")
    await aigul.click(texts.BTN_SKIP)
    wrong = await save(aigul, 3)
    wrong_id = int(wrong.split("№")[1].split()[0])
    await aigul.click(texts.BTN_OPEN_RECORD)
    await aigul.click(texts.BTN_CANCEL_RECORD)
    await aigul.send("ошибка в сумме: вернул 50 000")
    await aigul.click(texts.BTN_CONFIRM_CANCEL)
    cancellation_id = wrong_id + 1
    assert aigul.bot_messages[-2].text == f"Запись №{wrong_id} отменена записью №{cancellation_id}."
    await menu(aigul)
    await aigul.click(texts.BTN_LOANS)
    await aigul.click(texts.BTN_LOAN_REPAY_IN)
    await aigul.click("Бекзат")
    await aigul.send("50 000")
    await aigul.click(texts.BTN_SKIP)
    await save(aigul, 3)

    assert (await card_of(owner, "Бекзат")).endswith("Обязательств нет")
    assert (await balances(owner))[-1] == "Наличка: 727 990 KGS"
    # Both owners heard about the cancellation.
    for chat in (OWNER_TG_ID, SECOND_OWNER_TG_ID):
        notices = [m for m in harness.chat(chat) if m.text.startswith("Помощник отменил запись")]
        assert len(notices) == 1
        assert f"Запись №{wrong_id}: Мне вернули · Бекзат · 5 000 KGS" in notices[0].text
    # The owner sees no «Отменить запись» on Айгуль's record.
    notice = next(
        m for m in harness.chat(OWNER_TG_ID) if m.text.startswith("Помощник отменил запись")
    )
    await owner.click(texts.BTN_OPEN_RECORD, message=notice)
    assert texts.BTN_CANCEL_RECORD not in owner.last.button_texts
    # Neither the cancelled record nor the cancellation can be cancelled.
    for record_id in (wrong_id, cancellation_id):
        await menu(aigul)
        await aigul.click(texts.BTN_BALANCES)
        await aigul.click(texts.BTN_DAY_RECORDS)
        row = next(text for text in aigul.last.button_texts if text.startswith(f"№{record_id} "))
        await aigul.click(row)
        assert texts.BTN_CANCEL_RECORD not in aigul.last.button_texts
    # Opening balances are only shown now.
    await menu(owner)
    await owner.click(texts.BTN_SETTINGS)
    await owner.click(texts.BTN_OPENING)
    assert texts.OPENING_FROZEN in owner.last.text
    assert texts.BTN_ENTER not in owner.last.button_texts
