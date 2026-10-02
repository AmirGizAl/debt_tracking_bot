"""Choosing a client inside a scenario (TZ 13.3 step 6, 13.5 step 1).

Recent clients, a search by any typed text, or a new client. The scenario that starts the
picker registers what happens with the chosen client (`on_picked`) and where "Назад" leads
from the first screen of the picker (`on_back`).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import client_picker as kb
from app.bot.states import ClientPick
from app.bot.ui import show_step
from app.db.models import Client, User
from app.services import clients

Event = Message | CallbackQuery
Picked = Callable[[Event, FSMContext, Bot, AsyncSession, User, Client], Awaitable[None]]
Back = Callable[[Event, FSMContext, Bot, AsyncSession, User], Awaitable[None]]

TARGET_KEY = "pick_target"
TITLE_KEY = "pick_title"
QUERY_KEY = "pick_query"  # None: the recent clients; "": the search prompt; else the results
NEW_NAME_KEY = "pick_new_name"


@dataclass(frozen=True)
class Target:
    on_picked: Picked
    on_back: Back
    allow_new: bool = True


_TARGETS: dict[str, Target] = {}


def register(name: str, target: Target) -> None:
    _TARGETS[name] = target


def target_of(data: dict[str, Any]) -> Target | None:
    return _TARGETS.get(data.get(TARGET_KEY) or "")


async def start(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, *, target: str, title: str
) -> None:
    await state.update_data({TARGET_KEY: target, TITLE_KEY: title, NEW_NAME_KEY: None})
    await show_choose(event, state, bot, session)


async def show_choose(event: Event, state: FSMContext, bot: Bot, session: AsyncSession) -> None:
    data = await state.update_data({QUERY_KEY: None})
    target = target_of(data)
    assert target is not None
    recent = await clients.recent_clients(session)
    await state.set_state(ClientPick.choose)
    await show_step(
        event,
        state,
        bot,
        texts.client_step(data[TITLE_KEY], bool(recent)),
        kb.choose(recent, target.allow_new),
    )


async def show_search_prompt(event: Event, state: FSMContext, bot: Bot) -> None:
    data = await state.update_data({QUERY_KEY: ""})
    await state.set_state(ClientPick.choose)
    await show_step(event, state, bot, f"{data[TITLE_KEY]}\n\n{texts.ASK_SEARCH}", kb.back_only())


async def show_results(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, query: str, number: int
) -> None:
    data = await state.update_data({QUERY_KEY: query})
    target = target_of(data)
    assert target is not None
    page = await clients.search_clients(session, query, number)
    await state.set_state(ClientPick.choose)
    await show_step(
        event,
        state,
        bot,
        f"{data[TITLE_KEY]}\n\n{texts.search_results(query, page.total)}",
        kb.results(page, target.allow_new),
    )


async def show_new_name(
    event: Event, state: FSMContext, bot: Bot, text: str = texts.ASK_NEW_CLIENT_NAME
) -> None:
    await state.set_state(ClientPick.new_name)
    await show_step(event, state, bot, text, kb.back_only())


async def show_new_comment(
    event: Event, state: FSMContext, bot: Bot, text: str = texts.ASK_CLIENT_COMMENT
) -> None:
    await state.set_state(ClientPick.new_comment)
    await show_step(event, state, bot, text, kb.new_comment())


async def go_back(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    current = await state.get_state()
    data = await state.get_data()
    target = target_of(data)
    assert target is not None
    if current == ClientPick.new_comment.state:
        await show_new_name(event, state, bot)
    elif current == ClientPick.new_name.state or data.get(QUERY_KEY) is not None:
        await show_choose(event, state, bot, session)
    else:
        await target.on_back(event, state, bot, session, user)
