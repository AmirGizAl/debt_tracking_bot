from aiogram.types import InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import BalancesAction, BalancesCb
from app.bot.keyboards.common import button, home_button, markup
from app.db.models import User


def screen(user: User) -> InlineKeyboardMarkup:
    row = [button(texts.BTN_DAY_RECORDS, BalancesCb(action=BalancesAction.RECORDS))]
    if user.is_owner:
        row.append(button(texts.BTN_ADJUST, BalancesCb(action=BalancesAction.ADJUST)))
    return markup(row, [home_button()])
