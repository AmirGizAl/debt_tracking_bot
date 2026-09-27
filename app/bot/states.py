from aiogram.fsm.state import State, StatesGroup


class HelperFlow(StatesGroup):
    username = State()
