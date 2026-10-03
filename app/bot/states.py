from aiogram.fsm.state import State, StatesGroup


class HelperFlow(StatesGroup):
    username = State()


class ClientsFlow(StatesGroup):
    search = State()
    add_name = State()
    add_comment = State()
    edit_name = State()
    edit_comment = State()


class OpeningFlow(StatesGroup):
    currency = State()
    amount = State()
    confirm = State()


class ExchangeFlow(StatesGroup):
    give_currency = State()
    get_currency = State()
    amount = State()  # the first amount: given, or got after "Ввести сумму, которую получает"
    rate = State()  # different currencies
    second_amount = State()  # one currency: the other amount is typed, not calculated
    mode = State()
    confirm = State()
    edit_amount = State()
    comment = State()


class ClientPick(StatesGroup):
    choose = State()  # recent clients, search prompt or results; typed text is a search
    new_name = State()
    new_comment = State()


class SettleFlow(StatesGroup):
    currency = State()  # started from the client card
    amount = State()
    confirm = State()


class LoanFlow(StatesGroup):
    amount = State()  # the client is chosen before, with the client picker
    comment = State()
    confirm = State()


class ReversalFlow(StatesGroup):
    reason = State()
    confirm = State()


class AdjustFlow(StatesGroup):
    currency = State()
    direction = State()
    amount = State()
    reason = State()
    confirm = State()


class DayReportFlow(StatesGroup):
    """The preliminary report and the closing of the day (TZ 7.2, 8.2, 8.3)."""

    rate = State()
    check = State()  # the numbers with the closing or the format buttons
