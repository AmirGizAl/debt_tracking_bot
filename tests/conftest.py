"""Shared fixtures. Tests run against a real PostgreSQL given by TEST_DATABASE_URL.

The schema is rebuilt once per session by the real Alembic migration (upgrade, downgrade,
upgrade again), and every test starts from empty tables (TRUNCATE ... RESTART IDENTITY).
Commits are real, so concurrency tests see each other's transactions.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import User, UserRole, UserStatus
from app.db.session import create_engine, create_sessionmaker

ROOT = Path(__file__).resolve().parent.parent
TABLES = ("operations", "cash_adjustments", "clients", "users")

OWNER_TG_ID = 1001


def _database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "TEST_DATABASE_URL is not set. Start the test database with\n"
            "  docker compose -f docker-compose.test.yml up -d\n"
            "and export TEST_DATABASE_URL="
            "postgresql+asyncpg://debtbot:debtbot@localhost:55432/debtbot_test",
            pytrace=False,
        )
    database = make_url(url).database or ""
    if "test" not in database:
        # The fixtures drop the whole schema: refuse to touch anything that is not a test DB.
        pytest.fail(f"Refusing to use database {database!r}: its name must contain 'test'")
    return url


def _alembic(connection: Connection, action: str, revision: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    config.attributes["configure_logger"] = False
    getattr(command, action)(config, revision)


@pytest.fixture(scope="session")
def database_url() -> str:
    return _database_url()


@pytest.fixture(scope="session")
async def migrated_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database_url, pool_size=10)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    # Downgrade in between proves that the migration is reversible.
    for action, revision in (("upgrade", "head"), ("downgrade", "base"), ("upgrade", "head")):
        async with engine.begin() as connection:
            await connection.run_sync(_alembic, action, revision)
    yield engine
    await engine.dispose()


@pytest.fixture
async def engine(migrated_engine: AsyncEngine) -> AsyncEngine:
    async with migrated_engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    return migrated_engine


@pytest.fixture
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
async def session(sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session


async def create_user(
    session: AsyncSession,
    *,
    telegram_id: int | None,
    username: str | None = None,
    full_name: str | None = None,
    role: UserRole = UserRole.HELPER,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    user = User(
        telegram_id=telegram_id,
        username=username,
        full_name=full_name,
        role=role,
        status=status,
    )
    session.add(user)
    await session.commit()
    return user


@pytest.fixture
async def owner(session: AsyncSession) -> User:
    return await create_user(
        session, telegram_id=OWNER_TG_ID, full_name="Владелец", role=UserRole.OWNER
    )


@pytest.fixture
async def helper(session: AsyncSession, owner: User) -> User:
    return await create_user(session, telegram_id=2002, username="aigul_k", full_name="Айгуль")
