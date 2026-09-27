from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole, UserStatus
from app.services import users


async def test_ensure_owner_creates_active_owner(session: AsyncSession) -> None:
    owner = await users.ensure_owner(session, 1001)

    assert owner.telegram_id == 1001
    assert owner.role == UserRole.OWNER
    assert owner.status == UserStatus.ACTIVE
    assert owner.activated_at is not None


async def test_ensure_owner_is_idempotent(session: AsyncSession) -> None:
    first = await users.ensure_owner(session, 1001)
    second = await users.ensure_owner(session, 1001)

    assert first.id == second.id
    assert await session.scalar(select(func.count()).select_from(User)) == 1


async def test_new_owner_id_marks_previous_owner_deleted(session: AsyncSession) -> None:
    old = await users.ensure_owner(session, 1001)
    new = await users.ensure_owner(session, 1002)
    await session.refresh(old)

    assert old.status == UserStatus.DELETED
    assert old.deleted_at is not None
    assert new.id != old.id
    assert new.status == UserStatus.ACTIVE
    assert await users.get_active_by_telegram_id(session, 1001) is None
    assert await users.get_active_by_telegram_id(session, 1002) == new


async def test_switching_owner_back_revives_the_same_row(session: AsyncSession) -> None:
    first = await users.ensure_owner(session, 1001)
    await users.ensure_owner(session, 1002)
    revived = await users.ensure_owner(session, 1001)

    assert revived.id == first.id
    assert revived.status == UserStatus.ACTIVE
    assert revived.deleted_at is None
