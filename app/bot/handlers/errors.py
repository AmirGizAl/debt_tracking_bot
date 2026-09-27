import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

from app.bot import texts
from app.bot.ui import answer
from app.domain.errors import PermissionDenied

logger = logging.getLogger(__name__)

router = Router(name="errors")


@router.errors()
async def on_error(event: ErrorEvent, bot: Bot) -> bool:
    exception = event.exception
    if isinstance(exception, PermissionDenied):
        logger.warning("Permission denied in update %s: %s", event.update.update_id, exception)
        text = texts.PERMISSION_DENIED
    else:
        logger.error("Unhandled error in update %s", event.update.update_id, exc_info=exception)
        text = texts.UNEXPECTED_ERROR

    callback = event.update.callback_query
    message = event.update.message
    try:
        if callback is not None:
            await answer(callback)
            chat_id = callback.message.chat.id if callback.message else callback.from_user.id
        elif message is not None:
            chat_id = message.chat.id
        else:
            return True
        await bot.send_message(chat_id, text)
    except TelegramAPIError as exc:
        logger.warning("Cannot report the error to the user: %s", exc)
    return True
