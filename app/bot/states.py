from aiogram.fsm.state import State, StatesGroup


class HelperFlow(StatesGroup):
    username = State()


class ClientsFlow(StatesGroup):
    search = State()
    add_name = State()
    add_comment = State()
    edit_name = State()
    edit_comment = State()


class OperationFlow(StatesGroup):
    client = State()  # recent clients, search prompt or results; typed text is a search
    new_client_name = State()
    new_client_comment = State()
    currency = State()  # currency of a new debt, or the debt a repayment closes
    pay_mode = State()
    pay_currency = State()
    amount = State()
    rate = State()
    date = State()
    custom_date = State()
    comment = State()
    confirm = State()


class AdjustmentFlow(StatesGroup):
    currency = State()
    direction = State()
    amount = State()
    reason = State()
    confirm = State()


class ReversalFlow(StatesGroup):
    reason = State()
    confirm = State()
