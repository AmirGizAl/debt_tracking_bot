"""The bot in groups: it answers nothing there, but tells the owner the id of a new group.

GROUP_CHAT_ID in .env picks the group for notifications (app/bot/notify.py). Finding out the
id of a group is the hard part, so when the owner adds the bot to a group, the bot sends the
owner the exact line for .env.
"""

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import JOIN_TRANSITION, ChatMemberUpdatedFilter
from aiogram.types import ChatMemberUpdated

from app.bot import texts
from app.bot.notify import notify_owner
from app.config import Settings

logger = logging.getLogger(__name__)

router = Router(name="group")


@router.my_chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION), F.chat.type != ChatType.PRIVATE)
async def added_to_group(event: ChatMemberUpdated, bot: Bot, settings: Settings) -> None:
    chat = event.chat
    logger.info(
        "Bot added to %s %r (chat_id=%s) by telegram_id=%s",
        chat.type,
        chat.title,
        chat.id,
        event.from_user.id,
    )
    if event.from_user.id != settings.owner_telegram_id:
        return
    connected = chat.id == settings.group_chat_id
    await notify_owner(bot, settings, texts.bot_added_to_group(chat.title, chat.id, connected))
