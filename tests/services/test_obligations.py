"""Lists of obligations: «Ждут выдачи», «Ждут оплаты» (TZ 13.4) and som loans (TZ 13.5)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, User
from app.domain.entries import OperationType
from app.services import days, obligations
from app.services.pagination import page_of
from tests.factories import make_client
from tests.services.accounting import KGS, RUB, USD, D, loan, open_balance, settle, swap


@pytest.fixture
async def people(session: AsyncSession, owner: User) -> dict[str, Client]:
    await days.ensure_open_day(session)
    await open_balance(session, owner, "10000", USD)
    await open_balance(session, owner, "1000000", KGS)
    return {
        name: await make_client(session, owner, name)
        for name in ("Азамат", "Бекзат", "Тимур", "Иван")
    }


@pytest.fixture
async def book(session: AsyncSession, owner: User, people: dict[str, Client]) -> None:
    azamat, bekzat, timur, ivan = people.values()
    later = {"paid_now": False}  # we pay out later: we owe the client
    owed = {"received_now": False}  # the client pays later: the client owes us
    # Exchanges: we owe Азамат 1 000 USD, Бекзат 3 000 USD and Тимур 99 000 RUB;
    # Тимур owes us 500 USD, Иван owes us 700 RUB.
    await swap(session, owner, "88500", RUB, "1000", USD, rate="88.5", client=azamat, **later)
    await swap(session, owner, "261000", KGS, "3000", USD, rate="87", client=bekzat, **later)
    await swap(session, owner, "500", USD, "43500", KGS, rate="87", client=timur, **owed)
    await swap(session, owner, "700", RUB, "693", KGS, rate="0.99", client=ivan, **owed)
    await swap(session, owner, "100000", RUB, "99000", RUB, client=timur, **later)
    # Som loans live in their own book and never show up in the lists of exchanges.
    await loan(session, owner, OperationType.LOAN_GIVE, bekzat, "50000")
    await loan(session, owner, OperationType.LOAN_GIVE, azamat, "20000")
    await loan(session, owner, OperationType.LOAN_TAKE, ivan, "100000")


def names(lines: list[obligations.ObligationLine]) -> list[tuple[str, str, str]]:
    return [(line.client, line.currency, str(line.amount)) for line in lines]


async def test_waiting_for_a_payout(session: AsyncSession, book: None) -> None:
    lines = await obligations.waiting(session, paying=True)

    # Grouped by currency in the display order, the largest first within a currency.
    assert names(lines) == [
        ("Бекзат", USD, "-3000.00"),
        ("Азамат", USD, "-1000.00"),
        ("Тимур", RUB, "-99000.00"),
    ]
    assert obligations.totals(lines) == {USD: D("4000"), RUB: D("99000")}


async def test_waiting_for_a_payment(session: AsyncSession, book: None) -> None:
    lines = await obligations.waiting(session, paying=False)

    assert names(lines) == [("Тимур", USD, "500.00"), ("Иван", RUB, "700.00")]
    assert obligations.totals(lines) == {USD: D("500"), RUB: D("700")}


async def test_settled_obligations_leave_the_list(
    session: AsyncSession, owner: User, people: dict[str, Client], book: None
) -> None:
    await settle(session, owner, OperationType.EXCHANGE_PAYOUT, people["Азамат"], "1000", USD)
    await settle(session, owner, OperationType.EXCHANGE_PAYOUT, people["Бекзат"], "1000", USD)

    lines = await obligations.waiting(session, paying=True)

    assert names(lines) == [("Бекзат", USD, "-2000.00"), ("Тимур", RUB, "-99000.00")]


async def test_loan_debts(session: AsyncSession, book: None) -> None:
    lines = await obligations.loan_debts(session)

    # First who owes us, then whom we owe; the largest first.
    assert names(lines) == [
        ("Бекзат", KGS, "50000.00"),
        ("Азамат", KGS, "20000.00"),
        ("Иван", KGS, "-100000.00"),
    ]


async def test_empty_lists(session: AsyncSession, people: dict[str, Client]) -> None:
    assert await obligations.waiting(session, paying=True) == []
    assert await obligations.loan_debts(session) == []
    assert obligations.totals([]) == {}


@pytest.mark.parametrize(
    ("page", "expected_page", "items"),
    [(0, 0, list(range(10))), (2, 2, [20, 21, 22]), (9, 2, [20, 21, 22]), (-1, 0, list(range(10)))],
)
def test_page_of_a_list(page: int, expected_page: int, items: list[int]) -> None:
    result = page_of(list(range(23)), page)

    assert (result.page, result.items, result.total, result.pages) == (
        expected_page,
        items,
        23,
        3,
    )


def test_page_of_an_empty_list() -> None:
    result = page_of([], 3)

    assert (result.page, result.items, result.pages) == (0, [], 1)
