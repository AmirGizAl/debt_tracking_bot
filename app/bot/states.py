from aiogram.fsm.state import State, StatesGroup


class HelperFlow(StatesGroup):
    username = State()


class ClientsFlow(StatesGroup):
    search = State()
    add_name = State()
    add_comment = State()
    edit_name = State()
    edit_comment = State()
