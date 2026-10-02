from collections.abc import AsyncIterator

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.bot.dispatcher import create_dispatcher
from app.config import Settings
from app.db.models import User
from app.db.session import create_sessionmaker
from app.services import days, users
from tests.bot.harness import BOT_TOKEN, FakeTelegram, Harness, JsonMemoryStorage, UserClient
from tests.conftest import OWNER_TG_ID, SECOND_OWNER_TG_ID
from tests.services.accounting import KGS, USD, open_balance


@pytest.fixture(scope="session")
def settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        bot_token=BOT_TOKEN,
        owner_telegram_ids=(OWNER_TG_ID, SECOND_OWNER_TG_ID),
        database_url=database_url,
        redis_url=None,
        tz="Europe/Moscow",
    )


@pytest.fixture(scope="session")
def dispatcher(migrated_engine: AsyncEngine, settings: Settings) -> Dispatcher:
    # aiogram routers attach to one dispatcher only, so the whole session shares it;
    # every test gets its own FSM storage and fake Telegram below.
    return create_dispatcher(settings, create_sessionmaker(migrated_engine))


@pytest.fixture
async def harness(
    dispatcher: Dispatcher,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> AsyncIterator[Harness]:
    async with sessionmaker() as session:
        # What the bot does on start (TZ 15.3): sync the owners, open day №1.
        await users.sync_owners(session, settings.owner_telegram_ids)
        await days.ensure_open_day(session)
    dispatcher.fsm.storage = JsonMemoryStorage()
    telegram = FakeTelegram()
    bot = Bot(
        token=BOT_TOKEN,
        session=telegram,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    yield Harness(dispatcher, bot, telegram)
    await dispatcher.fsm.storage.close()


@pytest.fixture
def owner_client(harness: Harness) -> UserClient:
    return harness.user(OWNER_TG_ID, username="boss", first_name="Владелец")


@pytest.fixture
def second_owner_client(harness: Harness) -> UserClient:
    return harness.user(SECOND_OWNER_TG_ID, first_name="Второй владелец")


@pytest.fixture
async def owner_user(harness: Harness, session: AsyncSession) -> User:
    user = await users.get_active_by_telegram_id(session, OWNER_TG_ID)
    assert user is not None
    return user


@pytest.fixture
async def funded(session: AsyncSession, owner_user: User) -> User:
    """TZ 17.1, scenario 1: 10 000 USD and 1 000 000 KGS; returns the owner."""
    await open_balance(session, owner_user, "10000", USD)
    await open_balance(session, owner_user, "1000000", KGS)
    return owner_user
