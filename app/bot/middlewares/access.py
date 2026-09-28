import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Chat, Message, TelegramObject
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards.common import main_menu, panel
from app.bot.notify import notify_group, notify_owner
from app.bot.ui import answer
from app.config import Settings
from app.db.models import User
from app.services import users

logger = logging.getLogger(__name__)

MEDIA_GROUP_TTL = 60.0


class AccessMiddleware(BaseMiddleware):
    """Outer middleware for Message and CallbackQuery (TZ 9.5).

    Passes the update on only for an active user and puts the db `User` into `data["user"]`.
    A pending helper is activated by username on their first update (TZ 9.3).
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._seen_media_groups: dict[str, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        chat: Chat | None = data.get("event_chat")
        if tg_user is None or tg_user.is_bot:
            return None
        if chat is not None and chat.type != ChatType.PRIVATE:
            return None
        if isinstance(event, Message) and self._repeated_media_group(event):
            # An album arrives as N messages; answer it once, not N times.
            return None

        session: AsyncSession = data["session"]
        user = await users.get_active_by_telegram_id(session, tg_user.id)
        if user is None and tg_user.id == self.settings.owner_telegram_id:
            user = await users.ensure_owner(session, tg_user.id)
        if user is None:
            activated = await users.activate_by_username(
                session, tg_user.id, tg_user.username, tg_user.full_name
            )
            if activated is not None:
                logger.info("Helper @%s activated", activated.username)
                await self._welcome(event, data["bot"], activated)
                return None
            logger.info("Access denied for telegram_id=%s (@%s)", tg_user.id, tg_user.username)
            await self._deny(event, has_username=bool(tg_user.username))
            return None

        if user.full_name is None:
            await users.update_full_name(session, user, tg_user.full_name)
        data["user"] = user
        return await handler(event, data)

    def _repeated_media_group(self, message: Message) -> bool:
        group_id = message.media_group_id
        if group_id is None:
            return False
        now = time.monotonic()
        for key, seen_at in list(self._seen_media_groups.items()):
            if now - seen_at > MEDIA_GROUP_TTL:
                del self._seen_media_groups[key]
        if group_id in self._seen_media_groups:
            return True
        self._seen_media_groups[group_id] = now
        return False

    async def _welcome(self, event: TelegramObject, bot: Bot, helper: User) -> None:
        if isinstance(event, CallbackQuery):
            await answer(event)
        assert helper.telegram_id is not None
        await bot.send_message(helper.telegram_id, texts.PANEL_GREETING, reply_markup=panel(helper))
        await bot.send_message(helper.telegram_id, texts.MAIN_MENU, reply_markup=main_menu(helper))
        notice = texts.helper_activated_notice(helper)
        await notify_owner(bot, self.settings, notice)
        await notify_group(bot, self.settings, notice)

    @staticmethod
    async def _deny(event: TelegramObject, has_username: bool) -> None:
        text = texts.no_access(has_username)
        if isinstance(event, CallbackQuery):
            await answer(event, text, alert=True)
        elif isinstance(event, Message):
            await event.answer(text)
