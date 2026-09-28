"""Repayment in another currency through the bot UI (TZ 4.5, 4.6, 12.4; scenarios 6-7)."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.db.models import Client, Operation, User
from app.domain.currency import Currency
from app.domain.errors import ConversionProblem, NumberProblem
from app.domain.operations import OperationType
from app.services import balances, cash
from tests.bot.harness import UserClient
from tests.bot.records import begin, save, today_text
from tests.factories import make_client
from tests.services.accounting import adjust, record

KGS, USD, EUR, RUB, KZT = Currency.KGS, Currency.USD, Currency.EUR, Currency.RUB, Currency.KZT


async def pay_other(
    client: UserClient,
    button: str,
    name: str,
    debt_button: str,
    pay_currency: str,
    amount: str,
) -> None:
    """Up to the rate question."""
    await begin(client, button, name)
    await client.click(debt_button)
    await client.click(texts.BTN_OTHER_CURRENCY)
    await client.click(pay_currency)
    await client.send(amount)


async def finish_steps(client: UserClient, rate: str) -> None:
    await client.send(rate)
    await client.click(texts.BTN_SKIP)


@pytest.fixture
async def state_after_5(session: AsyncSession, owner_user: User) -> tuple[Client, Client]:
    """TZ 15.1 after scenario 5: Азамат owes 600 USD, you owe Бекзат 30 000 RUB."""
    for amount, currency in (
        ("300000", KGS),
        ("10000", USD),
        ("2000", EUR),
        ("500000", RUB),
        ("1000000", KZT),
    ):
        await adjust(session, owner_user, amount, currency)
    azamat = await make_client(session, owner_user, "Азамат")
    bekzat = await make_client(session, owner_user, "Бекзат")
    await record(session, owner_user, azamat, OperationType.LEND, "1000")
    await record(session, owner_user, azamat, OperationType.REPAY_IN, "400")
    await record(session, owner_user, bekzat, OperationType.BORROW, "50000", RUB)
    await record(session, owner_user, bekzat, OperationType.REPAY_OUT, "20000", RUB)
    return azamat, bekzat


async def test_scenario_6_debt_in_usd_paid_in_kgs(
    owner_client: UserClient, session: AsyncSession, state_after_5: tuple[Client, Client]
) -> None:
    azamat, _ = state_after_5
    await begin(owner_client, texts.BTN_REPAY_IN, "Азамат")
    await owner_client.click("USD · должен 600")
    await owner_client.click(texts.BTN_OTHER_CURRENCY)
    assert owner_client.last.button_texts[:4] == ["KGS", "EUR", "RUB", "KZT"]
    await owner_client.click("KGS")
    assert owner_client.last.text.endswith("Введите сумму в KGS:")
    await owner_client.send("52 500")
    assert owner_client.last.text.endswith("Сколько сомов за 1 USD?")

    await finish_steps(owner_client, "87,5")

    assert owner_client.last.text == "\n".join(
        [
            "Проверьте запись",
            "Мне вернули: Азамат",
            "Получено: 52 500 KGS",
            "Курс: 1 USD = 87,5 KGS",
            "Закрывает долг: 600 USD",
            f"Дата: {today_text()}",
            "",
            "Сейчас:",
            "Азамат должен вам: 600 USD",
            "",
            "После сохранения:",
            "Азамат: долга в USD нет",
            "В кассе KGS: 352 500",
        ]
    )
    assert await save(owner_client) == "Запись №5 сохранена."
    assert await balances.client_balance(session, azamat.id, USD) == 0
    assert await cash.cash_balance(session, KGS) == Decimal("352500")
    assert await cash.cash_balance(session, USD) == Decimal("9400")  # USD cash untouched
    stored = await session.scalar(select(Operation).where(Operation.id == 5))
    assert stored is not None
    assert (stored.rate, stored.rate_base, stored.rate_quote) == (Decimal("87.5"), USD, KGS)


async def test_scenario_7_debt_in_rub_paid_in_usd(
    owner_client: UserClient, session: AsyncSession, state_after_5: tuple[Client, Client]
) -> None:
    _, bekzat = state_after_5
    await pay_other(
        owner_client, texts.BTN_REPAY_OUT, "Бекзат", "RUB · вы должны 30 000", "USD", "300"
    )
    assert owner_client.last.text.endswith("Сколько RUB за 1 USD?")

    await finish_steps(owner_client, "90")

    assert owner_client.last.text == "\n".join(
        [
            "Проверьте запись",
            "Я вернул: Бекзат",
            "Отдано: 300 USD",
            "Курс: 1 USD = 90 RUB",
            "Закрывает ваш долг: 27 000 RUB",
            f"Дата: {today_text()}",
            "",
            "Сейчас:",
            "Бекзат: вы должны 30 000 RUB",
            "",
            "После сохранения:",
            "Бекзат: вы должны 3 000 RUB",
            "В кассе USD: 9 100",
        ]
    )
    await save(owner_client)
    assert await balances.client_balance(session, bekzat.id, RUB) == Decimal("-3000")
    assert await cash.cash_balance(session, USD) == Decimal("9100")
    assert await cash.cash_balance(session, RUB) == Decimal("530000")


@pytest.mark.parametrize(
    ("debt_button", "pay_currency", "question"),
    [
        ("USD · должен 600", "KGS", "Сколько сомов за 1 USD?"),
        ("USD · должен 600", "EUR", "Сколько USD за 1 EUR?"),
        ("USD · должен 600", "RUB", "Сколько RUB за 1 USD?"),
        ("KGS", "KZT", "Сколько сомов за 1 KZT?"),
        ("RUB", "KZT", "Сколько KZT за 1 RUB?"),
    ],
)
async def test_rate_question_follows_the_pair_table(
    owner_client: UserClient,
    state_after_5: tuple[Client, Client],
    debt_button: str,
    pay_currency: str,
    question: str,
) -> None:
    await pay_other(owner_client, texts.BTN_REPAY_IN, "Азамат", debt_button, pay_currency, "100")

    assert owner_client.last.text.splitlines()[-1] == question


@pytest.mark.parametrize(
    ("typed", "problem"),
    [
        ("абв", texts.RATE_ERRORS[NumberProblem.FORMAT]),
        ("0", texts.RATE_ERRORS[NumberProblem.NOT_POSITIVE]),
        ("87,1234567", texts.RATE_ERRORS[NumberProblem.PRECISION]),
    ],
)
async def test_wrong_rate_keeps_the_step(
    owner_client: UserClient, state_after_5: tuple[Client, Client], typed: str, problem: str
) -> None:
    await pay_other(owner_client, texts.BTN_REPAY_IN, "Азамат", "USD · должен 600", "KGS", "1000")

    await owner_client.send(typed)

    lines = owner_client.last.text.split("\n\n")
    assert lines[-2:] == [problem, "Сколько сомов за 1 USD?"]
    await owner_client.send("87,5")
    assert owner_client.last.text == (
        f"Мне вернули: Азамат · 1 000 KGS\n\n{texts.ASK_RECORD_COMMENT}"
    )


async def test_rate_that_turns_payment_into_zero_is_refused(
    owner_client: UserClient, state_after_5: tuple[Client, Client]
) -> None:
    await pay_other(owner_client, texts.BTN_REPAY_IN, "Азамат", "USD · должен 600", "KGS", "0,01")

    await owner_client.send("87,5")  # 0.01 / 87.5 = 0.0001 -> 0.00 USD

    assert texts.CONVERSION_ERRORS[ConversionProblem.ZERO] in owner_client.last.text


async def test_rounded_conversion_on_confirmation(
    owner_client: UserClient, state_after_5: tuple[Client, Client]
) -> None:
    await pay_other(owner_client, texts.BTN_REPAY_IN, "Азамат", "USD · должен 600", "KGS", "1000")
    await finish_steps(owner_client, "87,5")

    assert "Закрывает долг: 11,43 USD" in owner_client.last.text
    assert "Азамат должен вам: 588,57 USD" in owner_client.last.text


async def test_overpayment_warning_uses_converted_amount(
    owner_client: UserClient, state_after_5: tuple[Client, Client]
) -> None:
    await pay_other(owner_client, texts.BTN_REPAY_IN, "Азамат", "USD · должен 600", "KGS", "60 000")
    await finish_steps(owner_client, "87,5")  # 685,71 USD against a 600 USD debt

    assert owner_client.last.text.endswith(
        "Внимание: сумма больше долга. Лишние 85,71 USD станут вашим долгом перед клиентом."
    )


async def test_cash_is_checked_in_payment_currency(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    bekzat = await make_client(session, owner_user, "Бекзат")
    await adjust(session, owner_user, "50000", RUB)
    await record(session, owner_user, bekzat, OperationType.BORROW, "30000", RUB)
    await adjust(session, owner_user, "299", USD)
    await begin(owner_client, texts.BTN_REPAY_OUT, "Бекзат")
    await owner_client.click("RUB · вы должны 30 000")
    await owner_client.click(texts.BTN_OTHER_CURRENCY)
    await owner_client.click("USD")
    assert "В кассе: 299 USD" in owner_client.last.text

    await owner_client.send("300")

    assert owner_client.last.text.endswith(
        "Недостаточно денег в кассе.\nВ кассе: 299 USD\nНужно: 300 USD\nВведите другую сумму:"
    )


async def test_back_through_other_currency_steps(
    owner_client: UserClient, state_after_5: tuple[Client, Client]
) -> None:
    await pay_other(owner_client, texts.BTN_REPAY_IN, "Азамат", "USD · должен 600", "KGS", "1000")
    await owner_client.send("87,5")  # now on the comment step
    screens = []
    for _ in range(5):
        await owner_client.click(texts.BTN_BACK)
        screens.append(owner_client.last.text.splitlines()[-1])

    assert screens == [
        "Сколько сомов за 1 USD?",
        "Введите сумму в KGS:",
        texts.ASK_PAY_CURRENCY,
        texts.PAY_MODE_QUESTION[OperationType.REPAY_IN],
        texts.ASK_DEBT_CURRENCY,
    ]


async def test_switching_back_to_same_currency_forgets_the_rate(
    owner_client: UserClient, session: AsyncSession, state_after_5: tuple[Client, Client]
) -> None:
    await pay_other(owner_client, texts.BTN_REPAY_IN, "Азамат", "USD · должен 600", "KGS", "1000")
    await owner_client.send("87,5")
    for _ in range(4):
        await owner_client.click(texts.BTN_BACK)  # back to "same or other currency"
    await owner_client.click(texts.BTN_SAME_CURRENCY)
    await owner_client.send("100")
    await owner_client.click(texts.BTN_SKIP)

    assert "Сумма: 100 USD" in owner_client.last.text
    await save(owner_client)
    stored = await session.scalar(select(Operation).order_by(Operation.id.desc()))
    assert stored is not None
    assert (stored.cash_currency, stored.rate) == (USD, None)
