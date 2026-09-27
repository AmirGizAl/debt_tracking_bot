"""Record scenarios: FSM data and the screen of every step (TZ 12.2-12.4).

Handlers in lend_borrow.py, repay.py and operation_steps.py react to input and call these
renderers. Every renderer sets the FSM state it shows, so "Назад" can be computed from the
current state and data alone.
"""

import uuid
from dataclasses import asdict, dataclass, fields
from datetime import date
from decimal import Decimal
from typing import Any

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import OpAction
from app.bot.keyboards import operations as kb
from app.bot.states import OperationFlow
from app.bot.ui import show_step
from app.domain.currency import Currency
from app.domain.money import format_money
from app.domain.operations import (
    REPAY_TYPES,
    OperationDraft,
    OperationTerms,
    OperationType,
    compute_terms,
    repay_warning,
    takes_cash,
)
from app.domain.rates import rate_pair
from app.services import balances, cash, clients

Event = Message | CallbackQuery


@dataclass
class Flow:
    """Everything the user has entered so far. Stored in FSM data as plain strings."""

    op_type: OperationType
    request_id: str
    client_id: int | None = None
    client_name: str | None = None
    debt_currency: Currency | None = None
    other_currency: bool = False
    pay_currency: Currency | None = None
    amount: Decimal | None = None
    rate: Decimal | None = None
    op_date: date | None = None
    comment: str | None = None
    query: str | None = None
    new_client_name: str | None = None

    @property
    def is_repay(self) -> bool:
        return self.op_type in REPAY_TYPES

    @property
    def cash_currency(self) -> Currency:
        currency = self.pay_currency if self.other_currency else self.debt_currency
        assert currency is not None
        return currency

    @property
    def rate_pair(self) -> tuple[Currency, Currency]:
        assert self.debt_currency is not None and self.pay_currency is not None
        return rate_pair(self.debt_currency, self.pay_currency)

    def draft(self) -> OperationDraft:
        assert self.client_id is not None and self.debt_currency is not None
        assert self.amount is not None and self.op_date is not None
        return OperationDraft(
            request_id=uuid.UUID(self.request_id),
            type=self.op_type,
            client_id=self.client_id,
            debt_currency=self.debt_currency,
            cash_currency=self.cash_currency,
            cash_amount=self.amount,
            op_date=self.op_date,
            rate=self.rate if self.other_currency else None,
            comment=self.comment,
        )

    def dump(self) -> dict[str, Any]:
        """JSON-safe: RedisStorage keeps FSM data as JSON."""
        result: dict[str, Any] = {}
        for key, value in asdict(self).items():
            if isinstance(value, Decimal | Currency | OperationType):
                value = str(value)
            elif isinstance(value, date):
                value = value.isoformat()
            result[key] = value
        return result

    @classmethod
    def load(cls, data: dict[str, Any]) -> "Flow | None":
        if "op_type" not in data or "request_id" not in data:
            return None
        converters: dict[str, Any] = {
            "op_type": OperationType,
            "debt_currency": Currency,
            "pay_currency": Currency,
            "amount": Decimal,
            "rate": Decimal,
            "op_date": date.fromisoformat,
        }
        values = {}
        for field in fields(cls):
            value = data.get(field.name)
            if value is not None and field.name in converters:
                value = converters[field.name](value)
            if value is not None:
                values[field.name] = value
        return cls(**values)


async def load(state: FSMContext) -> Flow | None:
    return Flow.load(await state.get_data())


async def store(state: FSMContext, flow: Flow) -> None:
    await state.update_data(flow.dump())


async def start(state: FSMContext, op_type: OperationType) -> Flow:
    """A fresh scenario with its idempotency key (TZ 7.7)."""
    flow = Flow(op_type=op_type, request_id=str(uuid.uuid4()))
    await state.set_data(flow.dump())
    return flow


def header(flow: Flow) -> str:
    assert flow.client_name is not None
    return texts.record_header(flow.op_type, flow.client_name)


def summary(flow: Flow) -> str:
    """ "Выдал в долг: Азамат · 1 000 USD" for the date and comment steps."""
    assert flow.amount is not None
    return f"{header(flow)} · {format_money(flow.amount, flow.cash_currency)}"


# --- steps ---------------------------------------------------------------------------------


async def show_client_step(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, flow: Flow
) -> None:
    flow.query = None
    await store(state, flow)
    recent = await clients.recent_clients(session)
    await state.set_state(OperationFlow.client)
    await show_step(
        event, state, bot, texts.client_step(flow.op_type, bool(recent)), kb.client_step(recent)
    )


async def show_search_prompt(event: Event, state: FSMContext, bot: Bot, flow: Flow) -> None:
    flow.query = ""
    await store(state, flow)
    await state.set_state(OperationFlow.client)
    await show_step(event, state, bot, texts.ASK_SEARCH, kb.back_only())


async def show_search_results(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, flow: Flow, number: int
) -> None:
    assert flow.query
    await store(state, flow)
    page = await clients.search_clients(session, flow.query, number)
    await state.set_state(OperationFlow.client)
    await show_step(
        event, state, bot, texts.search_results(flow.query, page.total), kb.search_results(page)
    )


async def show_new_client_name(
    event: Event, state: FSMContext, bot: Bot, text: str = texts.ASK_NEW_CLIENT_NAME
) -> None:
    await state.set_state(OperationFlow.new_client_name)
    await show_step(event, state, bot, text, kb.back_only())


async def show_new_client_comment(
    event: Event, state: FSMContext, bot: Bot, text: str = texts.ASK_CLIENT_COMMENT
) -> None:
    await state.set_state(OperationFlow.new_client_comment)
    await show_step(event, state, bot, text, kb.skip_or_back(OpAction.SKIP_CLIENT_COMMENT))


async def show_currency_step(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, flow: Flow
) -> None:
    assert flow.client_id is not None and flow.client_name is not None
    await state.set_state(OperationFlow.currency)
    if flow.is_repay:
        client_balances = await balances.client_balances(session, flow.client_id)
        text = texts.debt_currency_step(flow.op_type, flow.client_name, client_balances)
        await show_step(event, state, bot, text, kb.debt_currencies(client_balances))
    else:
        text = texts.currency_step(flow.op_type, flow.client_name)
        await show_step(event, state, bot, text, kb.currencies())


async def show_pay_mode(event: Event, state: FSMContext, bot: Bot, flow: Flow) -> None:
    assert flow.client_name is not None and flow.debt_currency is not None
    await state.set_state(OperationFlow.pay_mode)
    text = texts.pay_mode_step(flow.op_type, flow.client_name, flow.debt_currency)
    await show_step(event, state, bot, text, kb.pay_mode())


async def show_pay_currency(event: Event, state: FSMContext, bot: Bot, flow: Flow) -> None:
    assert flow.debt_currency is not None
    await state.set_state(OperationFlow.pay_currency)
    text = f"{header(flow)}\nДолг в {flow.debt_currency}.\n\n{texts.ASK_PAY_CURRENCY}"
    await show_step(event, state, bot, text, kb.pay_currencies(flow.debt_currency))


async def show_amount(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    flow: Flow,
    problem: str | None = None,
) -> None:
    assert flow.client_name is not None and flow.debt_currency is not None
    currency = flow.cash_currency
    available = await cash.cash_balance(session, currency) if takes_cash(flow.op_type) else None
    text = texts.amount_step(
        flow.op_type, flow.client_name, currency, flow.debt_currency, available, problem
    )
    await state.set_state(OperationFlow.amount)
    await show_step(event, state, bot, text, kb.back_only())


async def show_rate(
    event: Event, state: FSMContext, bot: Bot, flow: Flow, problem: str | None = None
) -> None:
    assert flow.amount is not None and flow.debt_currency is not None
    base, quote = flow.rate_pair
    paid = format_money(flow.amount, flow.cash_currency)
    parts = [f"{header(flow)}\nОплата: {paid}, долг в {flow.debt_currency}."]
    if problem:
        parts.append(problem)
    parts.append(f"<b>{texts.rate_question(base, quote)}</b>")
    await state.set_state(OperationFlow.rate)
    text = "\n\n".join(parts)
    await show_step(event, state, bot, text, kb.back_only())


async def show_date(event: Event, state: FSMContext, bot: Bot, flow: Flow) -> None:
    await state.set_state(OperationFlow.date)
    await show_step(event, state, bot, texts.date_step(summary(flow)), kb.dates())


async def show_custom_date(
    event: Event, state: FSMContext, bot: Bot, text: str = texts.ASK_CUSTOM_DATE
) -> None:
    await state.set_state(OperationFlow.custom_date)
    await show_step(event, state, bot, text, kb.back_only())


async def show_comment(
    event: Event, state: FSMContext, bot: Bot, flow: Flow, problem: str | None = None
) -> None:
    text = f"{summary(flow)}\n\n{problem or texts.ASK_RECORD_COMMENT}"
    await state.set_state(OperationFlow.comment)
    await show_step(event, state, bot, text, kb.skip_or_back(OpAction.SKIP_COMMENT))


async def confirmation_text(session: AsyncSession, flow: Flow, terms: OperationTerms) -> str:
    """The "Проверьте запись" screen with the live balance and cash after saving."""
    assert flow.client_id is not None and flow.debt_currency is not None
    assert flow.op_date is not None
    client = await clients.get_client(session, flow.client_id)
    balance = await balances.client_balance(session, client.id, flow.debt_currency)
    cash_now = await cash.cash_balance(session, flow.cash_currency)
    return texts.confirm_record(
        op_type=flow.op_type,
        client_name=client.name,
        amounts=texts.amount_lines(
            flow.op_type,
            terms.debt_amount,
            flow.debt_currency,
            terms.cash_amount,
            flow.cash_currency,
            terms.rate,
            terms.rate_base,
            terms.rate_quote,
        ),
        op_date=flow.op_date,
        comment=flow.comment,
        balance_after=balance + terms.debt_delta,
        debt_currency=flow.debt_currency,
        cash_after=cash_now + terms.cash_delta,
        cash_currency=flow.cash_currency,
        warning=repay_warning(flow.op_type, balance, terms.debt_amount),
    )


async def show_confirm(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, flow: Flow
) -> None:
    text = await confirmation_text(session, flow, compute_terms(flow.draft()))
    await state.set_state(OperationFlow.confirm)
    await show_step(event, state, bot, text, kb.confirm())


# --- navigation ------------------------------------------------------------------------------


async def after_client(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, flow: Flow
) -> None:
    await store(state, flow)
    await show_currency_step(event, state, bot, session, flow)


async def after_amount(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, flow: Flow
) -> None:
    await store(state, flow)
    if flow.other_currency:
        await show_rate(event, state, bot, flow)
    else:
        await show_date(event, state, bot, flow)


async def go_back(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, flow: Flow
) -> None:
    """Show the step before the current one (TZ 11: "Назад" on every step)."""
    current = await state.get_state()
    if current in (OperationFlow.client.state, OperationFlow.new_client_name.state):
        await show_client_step(event, state, bot, session, flow)
    elif current == OperationFlow.new_client_comment.state:
        await show_new_client_name(event, state, bot)
    elif current == OperationFlow.currency.state:
        await show_client_step(event, state, bot, session, flow)
    elif current == OperationFlow.pay_mode.state:
        await show_currency_step(event, state, bot, session, flow)
    elif current == OperationFlow.pay_currency.state:
        await show_pay_mode(event, state, bot, flow)
    elif current == OperationFlow.amount.state:
        if not flow.is_repay:
            await show_currency_step(event, state, bot, session, flow)
        elif flow.other_currency:
            await show_pay_currency(event, state, bot, flow)
        else:
            await show_pay_mode(event, state, bot, flow)
    elif current == OperationFlow.rate.state:
        await show_amount(event, state, bot, session, flow)
    elif current == OperationFlow.date.state:
        if flow.other_currency:
            await show_rate(event, state, bot, flow)
        else:
            await show_amount(event, state, bot, session, flow)
    elif current in (OperationFlow.custom_date.state, OperationFlow.comment.state):
        await show_date(event, state, bot, flow)
    elif current == OperationFlow.confirm.state:
        await show_comment(event, state, bot, flow)
