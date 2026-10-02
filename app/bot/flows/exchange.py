"""The exchange scenario (TZ 13.3): data kept in FSM and the screen of every step.

give currency -> get currency -> amount (given, or got) -> rate (two currencies) or the
second amount (one currency) -> how it goes -> client (unless instant) -> confirmation.
Every renderer sets the state it shows, so "Назад" is computed from the state and the data.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import changes, texts
from app.bot.callbacks import ExchangeAction
from app.bot.flows import client_picker
from app.bot.flows.records import StoredForm
from app.bot.keyboards import exchange as kb
from app.bot.states import ExchangeFlow
from app.bot.ui import leave_any, show_step
from app.domain.currency import Currency
from app.domain.entries import ExchangeTerms, exchange_draft
from app.domain.rates import rate_pair
from app.services import exchange

Event = Message | CallbackQuery

PICK_FOR_DEAL = "exchange"  # the client step of a deferred exchange
PICK_FOR_CONFIRM = "exchange_confirm"  # «Указать клиента» on the confirmation

MODES = {
    "now": (True, True),
    "received": (True, False),
    "paid": (False, True),
    "later": (False, False),
}


@dataclass
class Form(StoredForm):
    """Everything entered so far."""

    request_id: str
    give_currency: Currency | None = None
    get_currency: Currency | None = None
    side: str = "give"  # the amount typed first: "give" or "get"
    give_amount: Decimal | None = None
    get_amount: Decimal | None = None
    rate: Decimal | None = None
    received_now: bool | None = None
    paid_now: bool | None = None
    client_id: int | None = None
    client_name: str | None = None
    comment: str | None = None

    @property
    def same_currency(self) -> bool:
        return self.give_currency == self.get_currency

    @property
    def instant(self) -> bool:
        return bool(self.received_now and self.paid_now)

    @property
    def typed_currency(self) -> Currency:
        currency = self.give_currency if self.side == "give" else self.get_currency
        assert currency is not None
        return currency

    @property
    def other_side(self) -> str:
        """The amount calculated by the rate (or typed second for one currency)."""
        return "get" if self.side == "give" else "give"

    @property
    def other_currency(self) -> Currency:
        currency = self.get_currency if self.side == "give" else self.give_currency
        assert currency is not None
        return currency

    def amount_of(self, side: str) -> Decimal | None:
        return self.give_amount if side == "give" else self.get_amount

    def set_amount(self, side: str, value: Decimal | None) -> None:
        if side == "give":
            self.give_amount = value
        else:
            self.get_amount = value

    def terms(self) -> ExchangeTerms:
        assert self.give_currency is not None and self.get_currency is not None
        assert self.give_amount is not None and self.get_amount is not None
        assert self.received_now is not None and self.paid_now is not None
        return ExchangeTerms(
            give_currency=self.give_currency,
            give_amount=self.give_amount,
            get_currency=self.get_currency,
            get_amount=self.get_amount,
            received_now=self.received_now,
            paid_now=self.paid_now,
            rate=None if self.same_currency else self.rate,
        )


async def load(state: FSMContext) -> Form | None:
    return Form.load(await state.get_data())


async def store(state: FSMContext, form: Form) -> None:
    await state.update_data(form.dump())


def line(form: Form) -> str:
    return texts.exchange_line(
        form.give_currency, form.give_amount, form.get_currency, form.get_amount
    )


def rate_line(form: Form) -> str | None:
    if form.same_currency or form.rate is None:
        return None
    assert form.give_currency is not None and form.get_currency is not None
    base, quote = rate_pair(form.give_currency, form.get_currency)
    return texts.rate_text(form.rate, base, quote)


def summary(form: Form) -> str:
    """Title of the later steps: the deal and its rate."""
    text = f"{texts.EXCHANGE_TITLE}\n{line(form)}"
    rate = rate_line(form)
    return f"{text}\nКурс: {rate}" if rate else text


async def begin(event: Event, state: FSMContext, bot: Bot) -> None:
    """Open the scenario from the main menu or from the panel; a fresh idempotency key."""
    await leave_any(event, state, bot)
    form = Form(request_id=str(uuid.uuid4()))
    await state.set_data(form.dump())
    await show_give_currency(event, state, bot)


# --- steps ---------------------------------------------------------------------------------------


async def show_give_currency(event: Event, state: FSMContext, bot: Bot) -> None:
    await state.set_state(ExchangeFlow.give_currency)
    text = f"{texts.EXCHANGE_TITLE}\n\n<b>{texts.ASK_GIVE_CURRENCY}</b>"
    await show_step(event, state, bot, text, kb.currencies(ExchangeAction.GIVE, first_step=True))


async def show_get_currency(event: Event, state: FSMContext, bot: Bot, form: Form) -> None:
    await state.set_state(ExchangeFlow.get_currency)
    text = texts.exchange_step(line(form), texts.ASK_GET_CURRENCY)
    await show_step(event, state, bot, text, kb.currencies(ExchangeAction.GET))


async def show_amount(
    event: Event, state: FSMContext, bot: Bot, form: Form, problem: str | None = None
) -> None:
    if form.side == "give":
        question = texts.ask_give_amount(form.typed_currency)
        switch = texts.BTN_ENTER_GET_AMOUNT
    else:
        question = texts.ask_get_amount(form.typed_currency)
        switch = texts.BTN_ENTER_GIVE_AMOUNT
    await state.set_state(ExchangeFlow.amount)
    text = texts.exchange_step(line(form), question, problem)
    await show_step(event, state, bot, text, kb.amount_step(switch))


async def show_rate(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    form: Form,
    problem: str | None = None,
) -> None:
    assert form.give_currency is not None and form.get_currency is not None
    base, quote = rate_pair(form.give_currency, form.get_currency)
    last = await exchange.last_rate_today(session, base, quote)
    await state.set_state(ExchangeFlow.rate)
    text = texts.exchange_step(line(form), texts.rate_question(base, quote), problem)
    label = texts.btn_last_rate(last) if last is not None else None
    await show_step(event, state, bot, text, kb.rate_step(label))


async def show_second_amount(
    event: Event, state: FSMContext, bot: Bot, form: Form, problem: str | None = None
) -> None:
    if form.other_side == "get":
        question = texts.ask_get_amount(form.other_currency)
    else:
        question = texts.ask_give_amount(form.other_currency)
    await state.set_state(ExchangeFlow.second_amount)
    await show_step(
        event, state, bot, texts.exchange_step(line(form), question, problem), kb.back_only()
    )


async def show_mode(
    event: Event, state: FSMContext, bot: Bot, form: Form, problem: str | None = None
) -> None:
    await state.set_state(ExchangeFlow.mode)
    parts = [summary(form)]
    if problem:
        parts.append(problem)
    parts.append(f"<b>{texts.ASK_MODE}</b>")
    await show_step(event, state, bot, "\n\n".join(parts), kb.modes())


async def show_client_step(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, form: Form
) -> None:
    await client_picker.start(event, state, bot, session, target=PICK_FOR_DEAL, title=summary(form))


async def after_lines(session: AsyncSession, form: Form) -> list[str]:
    """«После сохранения»: the balances and the client's obligations this exchange changes."""
    draft = exchange_draft(form.terms(), form.client_id)
    return await changes.after_lines(session, draft, form.client_name)


async def show_confirm(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, form: Form
) -> None:
    assert form.give_currency is not None and form.get_currency is not None
    assert form.give_amount is not None and form.get_amount is not None
    assert form.received_now is not None and form.paid_now is not None
    text = texts.confirm_exchange(
        client_name=form.client_name,
        give_currency=form.give_currency,
        give_amount=form.give_amount,
        get_currency=form.get_currency,
        get_amount=form.get_amount,
        received_now=form.received_now,
        paid_now=form.paid_now,
        rate_line=rate_line(form),
        comment=form.comment,
        after=await after_lines(session, form),
    )
    await state.set_state(ExchangeFlow.confirm)
    await show_step(event, state, bot, text, kb.confirm(form.instant))


async def show_edit_amount(
    event: Event, state: FSMContext, bot: Bot, form: Form, problem: str | None = None
) -> None:
    question = texts.ask_edit_amount(form.other_currency, gets=form.other_side == "get")
    await state.set_state(ExchangeFlow.edit_amount)
    await show_step(
        event, state, bot, texts.exchange_step(line(form), question, problem), kb.back_only()
    )


async def show_comment(
    event: Event, state: FSMContext, bot: Bot, problem: str | None = None
) -> None:
    form = await load(state)
    assert form is not None
    await state.set_state(ExchangeFlow.comment)
    text = texts.exchange_step(line(form), texts.ASK_EXCHANGE_COMMENT, problem)
    await show_step(event, state, bot, text, kb.back_only())


# --- navigation ----------------------------------------------------------------------------------


async def go_back(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, form: Form
) -> None:
    """The step before the current one (TZ 13.1: "Назад" on every step)."""
    current = await state.get_state()
    if current == ExchangeFlow.get_currency.state:
        await show_give_currency(event, state, bot)
    elif current == ExchangeFlow.amount.state:
        await show_get_currency(event, state, bot, form)
    elif current in (ExchangeFlow.rate.state, ExchangeFlow.second_amount.state):
        await show_amount(event, state, bot, form)
    elif current == ExchangeFlow.mode.state:
        if form.same_currency:
            await show_second_amount(event, state, bot, form)
        else:
            await show_rate(event, state, bot, session, form)
    elif current == ExchangeFlow.confirm.state:
        if form.instant:
            await show_mode(event, state, bot, form)
        else:
            await show_client_step(event, state, bot, session, form)
    else:  # edit_amount, comment
        await show_confirm(event, state, bot, session, form)
