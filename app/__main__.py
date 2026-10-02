import asyncio
import logging

from aiogram.exceptions import TelegramUnauthorizedError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.bot.dispatcher import (
    check_group,
    create_bot,
    create_dispatcher,
    create_storage,
    prepare_bot,
)
from app.config import Settings
from app.db.session import create_engine, create_sessionmaker
from app.logging import setup_logging
from app.services import days, users

logger = logging.getLogger("app")


async def wait_for_database(engine: AsyncEngine, attempts: int = 30, delay: float = 2.0) -> None:
    for attempt in range(1, attempts + 1):
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return
        except (OperationalError, OSError) as exc:
            if attempt == attempts:
                raise
            logger.warning("Database is not ready (%s/%s): %s", attempt, attempts, exc)
            await asyncio.sleep(delay)


async def run() -> None:
    settings = Settings()
    setup_logging(settings.log_level, settings.zone)
    engine = create_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)
    bot = create_bot(settings)
    try:
        await wait_for_database(engine)
        async with sessionmaker() as session:
            await users.sync_owners(session, settings.owner_telegram_ids)
            day = await days.ensure_open_day(session)
        dispatcher = create_dispatcher(settings, sessionmaker, create_storage(settings))
        await prepare_bot(bot)
        await check_group(bot, settings)
        logger.info(
            "Bot started, owners telegram_id=%s, open day №%s",
            ",".join(map(str, settings.owner_telegram_ids)),
            day.id,
        )
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            close_bot_session=False,
        )
    except TelegramUnauthorizedError:
        logger.error("Telegram rejected BOT_TOKEN: check the token from @BotFather in .env")
        raise SystemExit(1) from None
    finally:
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
