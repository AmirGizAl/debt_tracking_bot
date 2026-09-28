"""TZ 15.1: acceptance scenarios 1-12 in a row on a clean database, only through the bot UI."""

from decimal import Decimal
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import RecordAction, RecordCb
from app.db.models import Client, Operation
from app.domain.currency import Currency
from app.services import balances, cash
from tests.bot.harness import Harness, UserClient
from tests.bot.records import begin, new_debt, repay_same, save

KGS, USD, EUR, RUB, KZT = Currency.KGS, Currency.USD, Currency.EUR, Currency.RUB, Currency.KZT


async def balance(session: AsyncSession, name: str, currency: Currency) -> Decimal:
    client = await session.scalar(select(Client).where(Client.name == name))
    assert client is not None
    return await balances.client_balance(session, client.id, currency)


async def cash_screen(client: UserClient) -> str:
    await client.send("/menu")
    await client.click(texts.BTN_CASH)
    return client.last.text


async def pay_other(
    client: UserClient, button: str, name: str, debt: str, pay: str, amount: str, rate: str
) -> None:
    await begin(client, button, name)
    await client.click(debt)
    await client.click(texts.BTN_OTHER_CURRENCY)
    await client.click(pay)
    await client.send(amount)
    await client.send(rate)
    await client.click(texts.BTN_SKIP)


async def test_acceptance_scenarios_1_to_12(
    harness: Harness, owner_client: UserClient, session: AsyncSession
) -> None:
    owner = owner_client

    # 1. Opening balances.
    for currency, amount in (
        ("KGS", "300 000"),
        ("USD", "10 000"),
        ("EUR", "2 000"),
        ("RUB", "500 000"),
        ("KZT", "1 000 000"),
    ):
        await owner.send("/menu")
        await owner.click(texts.BTN_CASH)
        await owner.click(texts.BTN_ADJUST)
        await owner.click(currency)
        await owner.click(texts.BTN_ADD_MONEY)
        await owner.send(amount)
        await owner.send("Остаток на начало работы")
        await save(owner)
    assert await cash_screen(owner) == (
        "Касса\nKGS: 300 000\nUSD: 10 000\nEUR: 2 000\nRUB: 500 000\nKZT: 1 000 000"
    )

    # 2. «Выдал в долг» Азамату 1 000 USD.
    await new_debt(owner, texts.BTN_LEND, "Азамат", "USD", "1 000", new=True)
    assert "Азамат должен вам: 1 000 USD\nВ кассе USD: 9 000" in owner.last.text
    await save(owner)

    # 3. «Мне вернули» от Азамата 400 USD.
    await repay_same(owner, texts.BTN_REPAY_IN, "Азамат", "USD · должен 1 000", "400")
    assert "Азамат должен вам: 600 USD\nВ кассе USD: 9 400" in owner.last.text
    await save(owner)

    # 4. «Взял в долг» у Бекзата 50 000 RUB.
    await new_debt(owner, texts.BTN_BORROW, "Бекзат", "RUB", "50 000", new=True)
    assert "Бекзат: вы должны 50 000 RUB\nВ кассе RUB: 550 000" in owner.last.text
    await save(owner)

    # 5. «Я вернул» Бекзату 20 000 RUB.
    await repay_same(owner, texts.BTN_REPAY_OUT, "Бекзат", "RUB · вы должны 50 000", "20 000")
    assert "Бекзат: вы должны 30 000 RUB\nВ кассе RUB: 530 000" in owner.last.text
    await save(owner)

    # 6. Azamat's USD debt paid with 52 500 KGS at 87,5.
    await pay_other(
        owner, texts.BTN_REPAY_IN, "Азамат", "USD · должен 600", "KGS", "52 500", "87,5"
    )
    assert "Азамат: долга в USD нет\nВ кассе KGS: 352 500" in owner.last.text
    await save(owner)
    assert await cash.cash_balance(session, USD) == Decimal("9400")

    # 7. Bekzat's RUB debt paid with 300 USD at "Сколько RUB за 1 USD?" = 90.
    await pay_other(
        owner, texts.BTN_REPAY_OUT, "Бекзат", "RUB · вы должны 30 000", "USD", "300", "90"
    )
    assert "Бекзат: вы должны 3 000 RUB\nВ кассе USD: 9 100" in owner.last.text
    await save(owner)

    # 8. 12 000 USD is more than the cash: refused, nothing written.
    records_before = await session.scalar(select(func.count()).select_from(Operation))
    await begin(owner, texts.BTN_LEND, "Азамат")
    await owner.click("USD")
    await owner.send("12 000")
    assert owner.last.text.endswith(
        "Недостаточно денег в кассе.\nВ кассе: 9 100 USD\nНужно: 12 000 USD\nВведите другую сумму:"
    )
    await owner.send("/cancel")
    assert await session.scalar(select(func.count()).select_from(Operation)) == records_before

    # 9. «Общая сводка» with USD 87,5, EUR 100, RUB 1,1, KZT 0,17.
    await owner.send("/menu")
    await owner.click(texts.BTN_REPORTS)
    await owner.click(texts.BTN_REPORT_SUMMARY)
    for rate in ("87,5", "100", "1,1", "0,17"):
        await owner.send(rate)
    await owner.click(texts.BTN_EXCEL)
    document = [m for m in owner.bot_messages if m.document_data][-1]
    assert document.document_data is not None
    workbook = load_workbook(BytesIO(document.document_data))
    table_1 = list(workbook["Касса и долги"].iter_rows(values_only=True))
    assert table_1[-5:] == [
        ("KGS", 352500, 0, 0, 0),
        ("USD", 9100, 0, 0, 0),
        ("EUR", 2000, 0, 0, 0),
        ("RUB", 530000, 0, 3000, -3000),
        ("KZT", 1000000, 0, 0, 0),
    ]
    table_2 = list(workbook["Касса в сомах"].iter_rows(values_only=True))
    assert table_2[-1][0] == "Итого"
    assert table_2[-1][3] == 2101750

    # 10. Иван: lend 1 000 USD, borrow 300 USD, borrow 20 000 RUB.
    await new_debt(owner, texts.BTN_LEND, "Иван", "USD", "1000", new=True)
    await save(owner)
    await new_debt(owner, texts.BTN_BORROW, "Иван", "USD", "300")
    await save(owner)
    await new_debt(owner, texts.BTN_BORROW, "Иван", "RUB", "20000")
    await save(owner)
    await owner.send("/menu")
    await owner.click(texts.BTN_CLIENTS)
    await owner.click("Иван")
    assert "USD: должен вам 700\nRUB: вы должны 20 000" in owner.last.text

    # 11. Нурлан: lend 100 USD, then 150 USD back with the overpayment warning.
    await new_debt(owner, texts.BTN_LEND, "Нурлан", "USD", "100", new=True)
    await save(owner)
    await repay_same(owner, texts.BTN_REPAY_IN, "Нурлан", "USD · должен 100", "150")
    assert owner.last.text.endswith(
        "Внимание: сумма больше долга. Лишние 50 USD станут вашим долгом перед клиентом."
    )
    await save(owner)
    assert await balance(session, "Нурлан", USD) == Decimal("-50")

    # 12. Helper Айгуль makes a mistake and cancels it.
    await owner.send("/menu")
    await owner.click(texts.BTN_SETTINGS)
    await owner.click(texts.BTN_HELPERS)
    await owner.click(texts.BTN_ADD)
    await owner.send("@aigul_k")
    aigul = harness.user(2002, username="aigul_k", first_name="Айгуль")
    await aigul.send("/start")
    assert owner.last.text == "Новый помощник в боте: Айгуль (@aigul_k)."

    await new_debt(owner, texts.BTN_LEND, "Тимур", "USD", "1000", new=True)
    await save(owner)
    usd_before = await cash.cash_balance(session, USD)

    await repay_same(aigul, texts.BTN_REPAY_IN, "Тимур", "USD · должен 1 000", "1000")
    result = await save(aigul)
    wrong_number = int(result.split("№")[1].split()[0])
    assert await balance(session, "Тимур", USD) == 0

    # The owner has no "Отменить запись" on Айгуль's record.
    await owner.send("/menu")
    await owner.click(texts.BTN_CASH)
    await owner.click(texts.BTN_MOVEMENTS)
    await owner.click(owner.last.button_texts[0])  # the newest line is Айгуль's record
    assert owner.last.text.startswith(f"Запись №{wrong_number} · Мне вернули")
    assert texts.BTN_CANCEL_RECORD not in owner.last.button_texts

    await aigul.click(texts.BTN_OPEN_RECORD)
    await aigul.click(texts.BTN_CANCEL_RECORD)
    await aigul.send("ошибка в сумме, должно быть 100")
    await aigul.click(texts.BTN_CONFIRM_CANCEL)
    assert aigul.bot_messages[-2].text == (
        f"Запись №{wrong_number} отменена.\nТимур должен вам: 1 000 USD"
    )
    assert await balance(session, "Тимур", USD) == Decimal("1000")
    assert await cash.cash_balance(session, USD) == usd_before
    assert owner.last.text.startswith("Помощник отменил запись\nКто: Айгуль (@aigul_k)")

    # The cancelled record cannot be cancelled again; the reversal has no cancel button.
    await aigul.send("/menu")
    await aigul.press(
        RecordCb(action=RecordAction.OPEN, operation_id=wrong_number).pack(), aigul.last
    )
    assert texts.BTN_CANCEL_RECORD not in aigul.last.button_texts
    assert f"Статус: отменена записью №{wrong_number + 1}" in aigul.last.text

    await repay_same(aigul, texts.BTN_REPAY_IN, "Тимур", "USD · должен 1 000", "100")
    await save(aigul)
    assert await balance(session, "Тимур", USD) == Decimal("900")
