"""Shared parts of the scenarios that create a record: their data in FSM."""

import types
import typing
from dataclasses import MISSING, asdict, dataclass, fields
from decimal import Decimal
from enum import Enum
from typing import Any, Self

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.ui import answer, chat_id_of, finish
from app.db.models import User

Event = Message | CallbackQuery


def _restore(hint: Any, value: Any) -> Any:
    kinds = typing.get_args(hint) if isinstance(hint, types.UnionType) else (hint,)
    for kind in kinds:
        if kind is Decimal or (isinstance(kind, type) and issubclass(kind, Enum)):
            return kind(value)
    return value


@dataclass
class StoredForm:
    """Scenario data kept in FSM as plain JSON values (RedisStorage stores JSON).

    Decimals and enums are stored as strings and restored by the types of the fields.
    """

    def dump(self) -> dict[str, Any]:
        return {
            key: str(value) if isinstance(value, Decimal | Enum) else value
            for key, value in asdict(self).items()
        }

    @classmethod
    def load(cls, data: dict[str, Any]) -> Self | None:
        """None when a required field is missing: the scenario data is gone."""
        hints = typing.get_type_hints(cls)
        values = {}
        for field in fields(cls):
            value = data.get(field.name)
            if value is None:
                if field.default is MISSING and field.default_factory is MISSING:
                    return None
                continue
            values[field.name] = _restore(hints[field.name], value)
        return cls(**values)


async def current_form[F: StoredForm](
    form_type: type[F],
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> F | None:
    """The scenario data, or None (and the menu) if it is gone, e.g. after a restart."""
    form = form_type.load(await state.get_data())
    if form is None:
        if isinstance(event, CallbackQuery):
            await answer(event, texts.STALE_ACTION)
        await finish(bot, state, chat_id_of(event), user, session, texts.STALE_ACTION)
    return form
