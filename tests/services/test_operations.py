"""services/operations and cash rules (TZ 7, 8, 16)."""

import asyncio
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import CashAdjustment, Client, Operation, User
from app.domain import errors
from app.domain.currency import Currency
from app.domain.operations import OperationDraft, OperationType
from app.services import balances, cash, operations
from tests.factories import make_client
from tests.services.accounting import TODAY, adjust, record, reverse

LEND, REPAY_IN, BORROW, REPAY_OUT = (
    OperationType.LEND,
    OperationType.REPAY_IN,
    OperationType.BORROW,
    OperationType.REPAY_OUT,
)
KGS, USD, EUR, RUB, KZT = Currency.KGS, Currency.USD, Currency.EUR, Currency.RUB, Currency.KZT
D = Decimal


@pytest.fixture
async def ivan(session: AsyncSession, owner: User) -> Client:
    return await make_client(session, owner, "Иван")


@pytest.fixture
async def azamat(session: AsyncSession, owner: User) -> Client:
    return await make_client(session, owner, "Азамат")


async def count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


# --- deltas and balances -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("op_type", "debt_delta", "cash_delta"),
    [
        (LEND, "100", "-100"),
        (REPAY_IN, "-100", "100"),
        (BORROW, "-100", "100"),
        (REPAY_OUT, "100", "-100"),
    ],
)
async def test_saved_deltas_by_type(
    session: AsyncSession,
    owner: User,
    ivan: Client,
    op_type: OperationType,
    debt_delta: str,
    cash_delta: str,
) -> None:
    await adjust(session, owner, "1000")

    operation = await record(session, owner, ivan, op_type, "100")

    assert (operation.debt_delta, operation.cash_delta) == (D(debt_delta), D(cash_delta))
    assert await balances.client_balance(session, ivan.id, USD) == D(debt_delta)
    assert await cash.cash_balance(session, USD) == D("1000") + D(cash_delta)


async def test_counter_debts_and_overpayment(
    session: AsyncSession, owner: User, ivan: Client
) -> None:
    nurlan = await make_client(session, owner, "Нурлан")
    await adjust(session, owner, "10000")

    # TZ 15.1 scenario 10: counter debts in one currency collapse, other currencies don't mix.
    await record(session, owner, ivan, LEND, "1000")
    await record(session, owner, ivan, BORROW, "300")
    await record(session, owner, ivan, BORROW, "20000", RUB)
    ivan_balances = await balances.client_balances(session, ivan.id)
    assert (ivan_balances[USD], ivan_balances[RUB]) == (D("700"), D("-20000"))

    # Scenario 11: overpayment turns into the owner's debt.
    await record(session, owner, nurlan, LEND, "100")
    await record(session, owner, nurlan, REPAY_IN, "150")
    assert await balances.client_balance(session, nurlan.id, USD) == D("-50")


async def test_acceptance_scenarios_1_to_8(session: AsyncSession, owner: User) -> None:
    azamat = await make_client(session, owner, "Азамат")
    bekzat = await make_client(session, owner, "Бекзат")
    for amount, currency in (
        ("300000", KGS),
        ("10000", USD),
        ("2000", EUR),
        ("500000", RUB),
        ("1000000", KZT),
    ):
        await adjust(session, owner, amount, currency)

    await record(session, owner, azamat, LEND, "1000")
    assert await cash.cash_balance(session, USD) == D("9000")
    await record(session, owner, azamat, REPAY_IN, "400")
    assert await balances.client_balance(session, azamat.id, USD) == D("600")
    await record(session, owner, bekzat, BORROW, "50000", RUB)
    assert await cash.cash_balance(session, RUB) == D("550000")
    await record(session, owner, bekzat, REPAY_OUT, "20000", RUB)
    assert await balances.client_balance(session, bekzat.id, RUB) == D("-30000")

    # 6: USD debt paid with 52 500 KGS at 1 USD = 87,5 KGS.
    await record(session, owner, azamat, REPAY_IN, "52500", USD, pay_currency=KGS, rate="87.5")
    assert await balances.client_balance(session, azamat.id, USD) == 0
    assert await cash.cash_balance(session, KGS) == D("352500")
    assert await cash.cash_balance(session, USD) == D("9400")

    # 7: RUB debt paid with 300 USD at 1 USD = 90 RUB.
    await record(session, owner, bekzat, REPAY_OUT, "300", RUB, pay_currency=USD, rate="90")
    assert await balances.client_balance(session, bekzat.id, RUB) == D("-3000")
    assert await cash.cash_balance(session, USD) == D("9100")

    # 8: not enough cash, nothing is written.
    before = await count(session, Operation)
    with pytest.raises(errors.InsufficientCash) as error:
        await record(session, owner, azamat, LEND, "12000")
    assert (error.value.currency, error.value.available, error.value.required) == (
        USD,
        D("9100"),
        D("12000"),
    )
    assert await count(session, Operation) == before

    assert await cash.cash_balances(session) == {
        KGS: D("352500"),
        USD: D("9100"),
        EUR: D("2000"),
        RUB: D("530000"),
        KZT: D("1000000"),
    }


# --- cash never goes negative ------------------------------------------------------------------


async def test_lend_needs_cash(session: AsyncSession, owner: User, ivan: Client) -> None:
    await adjust(session, owner, "9100")

    with pytest.raises(errors.InsufficientCash) as error:
        await record(session, owner, ivan, LEND, "12000")

    assert (error.value.available, error.value.required) == (D("9100"), D("12000"))


async def test_repay_out_same_currency_needs_cash(
    session: AsyncSession, owner: User, ivan: Client
) -> None:
    await adjust(session, owner, "100")
    await record(session, owner, ivan, BORROW, "5000")  # cash 5 100, you owe 5 000
    await record(session, owner, ivan, LEND, "5100")  # cash 0

    with pytest.raises(errors.InsufficientCash):
        await record(session, owner, ivan, REPAY_OUT, "100")


async def test_repay_out_in_other_currency_checks_payment_currency(
    session: AsyncSession, owner: User, ivan: Client
) -> None:
    await adjust(session, owner, "50000", RUB)
    await record(session, owner, ivan, BORROW, "30000", RUB)
    await adjust(session, owner, "299", USD)

    with pytest.raises(errors.InsufficientCash) as error:
        await record(session, owner, ivan, REPAY_OUT, "300", RUB, pay_currency=USD, rate="90")

    assert (error.value.currency, error.value.available, error.value.required) == (
        USD,
        D("299"),
        D("300"),
    )
    assert await balances.client_balance(session, ivan.id, RUB) == D("-30000")


async def test_reversal_of_repay_in_needs_cash(
    session: AsyncSession, owner: User, ivan: Client, azamat: Client
) -> None:
    await adjust(session, owner, "1000")
    await record(session, owner, ivan, LEND, "1000")  # cash 0
    received = await record(session, owner, ivan, REPAY_IN, "1000")  # cash 1 000
    await record(session, owner, azamat, LEND, "1000")  # cash 0 again

    with pytest.raises(errors.InsufficientCash) as error:
        await reverse(session, owner, received)

    assert (error.value.available, error.value.required) == (D("0"), D("1000"))
    assert await operations.reversal_of(session, received.id) is None


async def test_reversal_of_borrow_needs_cash(
    session: AsyncSession, owner: User, ivan: Client, azamat: Client
) -> None:
    borrowed = await record(session, owner, ivan, BORROW, "500")
    await record(session, owner, azamat, LEND, "500")

    with pytest.raises(errors.InsufficientCash):
        await reverse(session, owner, borrowed)


async def test_negative_adjustment_needs_cash(session: AsyncSession, owner: User) -> None:
    await adjust(session, owner, "100")

    with pytest.raises(errors.InsufficientCash):
        await adjust(session, owner, "-500", reason="Личные расходы")

    assert await count(session, CashAdjustment) == 1
    await adjust(session, owner, "-100", reason="Личные расходы")
    assert await cash.cash_balance(session, USD) == 0


async def test_refused_write_keeps_callers_objects_usable(
    session: AsyncSession, owner: User, ivan: Client
) -> None:
    # A rollback in the caller's session would expire `owner`, and the handler that shows the
    # main menu after "not enough cash" would crash with MissingGreenlet.
    with pytest.raises(errors.InsufficientCash):
        await record(session, owner, ivan, LEND, "1")

    assert owner.is_owner
    assert ivan.name == "Иван"


async def test_backdated_record_is_checked_against_current_cash(
    session: AsyncSession, owner: User, ivan: Client
) -> None:
    # TZ 7.4: only today's balance matters; a past balance may go negative.
    await adjust(session, owner, "1000")
    early = TODAY.replace(month=1)

    operation = await record(session, owner, ivan, LEND, "1000", op_date=early)

    assert operation.op_date == early


# --- concurrency and idempotency ---------------------------------------------------------------


def _slow_balance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Widen the check-then-insert window so an unprotected race would really happen."""
    original = cash.cash_balance

    async def slow(*args: Any, **kwargs: Any) -> Decimal:
        value = await original(*args, **kwargs)
        await asyncio.sleep(0.05)
        return value

    monkeypatch.setattr(cash, "cash_balance", slow)


async def _two_parallel_lends(
    sessionmaker: async_sessionmaker[AsyncSession], owner: User, client: Client
) -> list[Any]:
    async def lend() -> Any:
        async with sessionmaker() as session:
            return await record(session, owner, client, LEND, "6000")

    return await asyncio.gather(lend(), lend(), return_exceptions=True)


async def test_race_two_lends_of_60_percent(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    owner: User,
    ivan: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await adjust(session, owner, "10000")
    _slow_balance(monkeypatch)

    results = await _two_parallel_lends(sessionmaker, owner, ivan)

    saved = [r for r in results if isinstance(r, Operation)]
    refused = [r for r in results if isinstance(r, errors.InsufficientCash)]
    assert (len(saved), len(refused)) == (1, 1)
    assert refused[0].available == D("4000")
    assert await cash.cash_balance(session, USD) == D("4000")


async def test_race_is_real_without_the_lock(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    owner: User,
    ivan: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves the test above can fail: with the advisory lock disabled both lends pass.
    await adjust(session, owner, "10000")
    _slow_balance(monkeypatch)

    async def no_lock(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(cash, "lock_cash", no_lock)

    results = await _two_parallel_lends(sessionmaker, owner, ivan)

    assert all(isinstance(r, Operation) for r in results)
    assert await cash.cash_balance(session, USD) == D("-2000")


async def test_repeated_save_returns_the_first_record(
    session: AsyncSession, owner: User, ivan: Client
) -> None:
    await adjust(session, owner, "1000")
    request_id = uuid.uuid4()

    first = await record(session, owner, ivan, LEND, "600", request_id=request_id)
    draft = OperationDraft(request_id, LEND, ivan.id, USD, USD, D("600"), TODAY)
    again, created = await operations.create_operation(session, owner, draft)

    assert again.id == first.id
    assert created is False
    assert await count(session, Operation) == 1
    assert await cash.cash_balance(session, USD) == D("400")


@pytest.mark.parametrize("op_type", [LEND, REPAY_IN])
async def test_parallel_double_tap_saves_once(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    owner: User,
    ivan: Client,
    op_type: OperationType,
) -> None:
    await adjust(session, owner, "1000")
    draft = OperationDraft(uuid.uuid4(), op_type, ivan.id, USD, USD, D("600"), TODAY)

    async def save() -> tuple[Operation, bool]:
        async with sessionmaker() as other:
            return await operations.create_operation(other, owner, draft)

    (first, first_created), (second, second_created) = await asyncio.gather(save(), save())

    assert first.id == second.id
    assert sorted([first_created, second_created]) == [False, True]
    assert await count(session, Operation) == 1


async def test_record_for_deleted_client_is_refused(session: AsyncSession, owner: User) -> None:
    draft = OperationDraft(uuid.uuid4(), BORROW, 999, USD, USD, D("10"), TODAY)

    with pytest.raises(errors.ClientNotFound):
        await operations.create_operation(session, owner, draft)


async def test_comment_is_limited_to_500(session: AsyncSession, owner: User, ivan: Client) -> None:
    operation = await record(session, owner, ivan, BORROW, "10", comment="  " + "я" * 500)
    assert operation.comment == "я" * 500

    with pytest.raises(errors.TextTooLong):
        await record(session, owner, ivan, BORROW, "10", comment="я" * 501)


# --- reversal (TZ 8) ---------------------------------------------------------------------------


async def test_reversal_mirrors_the_original(
    session: AsyncSession, owner: User, helper: User, ivan: Client
) -> None:
    await adjust(session, owner, "5000")
    await record(session, owner, ivan, LEND, "1000")
    wrong = await record(session, helper, ivan, REPAY_IN, "1000", comment="наличными")

    reversal = await reverse(session, helper, wrong, " ошибка в сумме, должно быть 100 ")

    assert reversal.reversal_of_id == wrong.id
    assert reversal.reversal_reason == "ошибка в сумме, должно быть 100"
    assert reversal.author_id == helper.id
    assert reversal.op_date == TODAY
    assert reversal.comment is None
    assert reversal.type == wrong.type
    assert (reversal.debt_amount, reversal.cash_amount) == (wrong.debt_amount, wrong.cash_amount)
    assert wrong.debt_delta + reversal.debt_delta == 0
    assert wrong.cash_delta + reversal.cash_delta == 0
    assert await balances.client_balance(session, ivan.id, USD) == D("1000")
    assert await cash.cash_balance(session, USD) == D("4000")


async def test_reversal_of_payment_in_other_currency_restores_both(
    session: AsyncSession, owner: User, azamat: Client
) -> None:
    await adjust(session, owner, "10000", USD)
    await record(session, owner, azamat, LEND, "600")
    paid = await record(
        session, owner, azamat, REPAY_IN, "52500", USD, pay_currency=KGS, rate="87.5"
    )
    assert await balances.client_balance(session, azamat.id, USD) == 0

    reversal = await reverse(session, owner, paid)

    assert (reversal.rate, reversal.rate_base, reversal.rate_quote) == (D("87.5"), USD, KGS)
    assert await balances.client_balance(session, azamat.id, USD) == D("600")
    assert await cash.cash_balance(session, KGS) == 0
    assert await cash.cash_balance(session, USD) == D("9400")


async def test_only_the_author_can_reverse(
    session: AsyncSession, owner: User, helper: User, ivan: Client
) -> None:
    helpers_record = await record(session, helper, ivan, BORROW, "100")
    owners_record = await record(session, owner, ivan, BORROW, "100")

    with pytest.raises(errors.PermissionDenied):
        await reverse(session, owner, helpers_record)
    with pytest.raises(errors.PermissionDenied):
        await reverse(session, helper, owners_record)


async def test_record_can_be_reversed_only_once(
    session: AsyncSession, owner: User, ivan: Client
) -> None:
    borrowed = await record(session, owner, ivan, BORROW, "100")
    await reverse(session, owner, borrowed)

    with pytest.raises(errors.AlreadyReversed):
        await reverse(session, owner, borrowed)


async def test_reversal_cannot_be_reversed(
    session: AsyncSession, owner: User, ivan: Client
) -> None:
    borrowed = await record(session, owner, ivan, BORROW, "100")
    reversal = await reverse(session, owner, borrowed)

    with pytest.raises(errors.CannotReverseReversal):
        await reverse(session, owner, reversal)


async def test_repeated_reversal_request_is_idempotent(
    session: AsyncSession, owner: User, ivan: Client
) -> None:
    borrowed = await record(session, owner, ivan, BORROW, "100")
    request_id = uuid.uuid4()

    first = await reverse(session, owner, borrowed, request_id=request_id)
    second = await reverse(session, owner, borrowed, request_id=request_id)

    assert first.id == second.id
    assert await count(session, Operation) == 2


async def test_parallel_reversals_save_one(
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    owner: User,
    ivan: Client,
) -> None:
    borrowed = await record(session, owner, ivan, BORROW, "100")

    async def cancel() -> Any:
        async with sessionmaker() as other:
            return await reverse(other, owner, borrowed)

    results = await asyncio.gather(cancel(), cancel(), return_exceptions=True)

    assert sum(isinstance(r, Operation) for r in results) == 1
    assert sum(isinstance(r, errors.AlreadyReversed) for r in results) == 1


async def test_records_of_a_deleted_helper_cannot_be_reversed(
    session: AsyncSession, owner: User, helper: User, ivan: Client
) -> None:
    from app.services import users

    helpers_record = await record(session, helper, ivan, BORROW, "100")
    await users.delete_helper(session, owner, helper.id)

    with pytest.raises(errors.PermissionDenied):
        await reverse(session, helper, helpers_record)
    with pytest.raises(errors.PermissionDenied):
        await reverse(session, owner, helpers_record)


@pytest.mark.parametrize(
    ("reason", "error"), [("   ", errors.EmptyText), ("я" * 501, errors.TextTooLong)]
)
async def test_reversal_reason_is_required(
    session: AsyncSession, owner: User, ivan: Client, reason: str, error: type[Exception]
) -> None:
    borrowed = await record(session, owner, ivan, BORROW, "100")

    with pytest.raises(error):
        await reverse(session, owner, borrowed, reason)


def test_can_reverse_rules(owner: User) -> None:
    other = User(id=owner.id + 1)
    original = Operation(id=15, author_id=owner.id, reversal_of_id=None)
    reversal = Operation(id=17, author_id=owner.id, reversal_of_id=15)

    assert operations.can_reverse(owner, original, None)
    assert not operations.can_reverse(owner, original, reversal)
    assert not operations.can_reverse(owner, reversal, None)
    assert not operations.can_reverse(other, original, None)
