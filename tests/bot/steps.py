"""Steps shared by the tests of scenarios that create records."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.db.models import Operation
from tests.bot.harness import UserClient


async def save(client: UserClient, day: int = 1) -> str:
    """Press «Сохранить»; returns the result message (the main menu follows it)."""
    await client.click(texts.BTN_SAVE)
    result, menu = client.bot_messages[-2:]
    assert menu.text == texts.main_menu(day)
    return result.text


async def records(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Operation)) or 0
