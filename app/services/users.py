from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole, UserStatus


def _now() -> datetime:
    return datetime.now(UTC)


async def get_active_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(
        select(User).where(User.telegram_id == telegram_id, User.status == UserStatus.ACTIVE)
    )


async def ensure_owner(session: AsyncSession, telegram_id: int) -> User:
    """Create or update the owner from OWNER_TELEGRAM_ID (TZ 9.1).

    If the configured id changed, the previous owner is marked deleted: the old account loses
    access at once and its records stay in history as "(удалён)".
    """
    now = _now()
    previous_owners = await session.scalars(
        select(User).where(
            User.role == UserRole.OWNER,
            User.status != UserStatus.DELETED,
            User.telegram_id.is_distinct_from(telegram_id),
        )
    )
    for previous in previous_owners:
        previous.status = UserStatus.DELETED
        previous.deleted_at = now
    await session.flush()

    owner = await session.scalar(
        select(User).where(User.telegram_id == telegram_id, User.status != UserStatus.DELETED)
    )
    if owner is None:
        # Same person coming back (e.g. the id was switched back): revive their row.
        owner = await session.scalar(
            select(User)
            .where(User.telegram_id == telegram_id, User.status == UserStatus.DELETED)
            .order_by(User.id.desc())
            .limit(1)
        )
    if owner is None:
        owner = User(telegram_id=telegram_id, role=UserRole.OWNER, status=UserStatus.ACTIVE)
        session.add(owner)
    owner.role = UserRole.OWNER
    if owner.status != UserStatus.ACTIVE:
        owner.status = UserStatus.ACTIVE
        owner.activated_at = now
        owner.deleted_at = None
    owner.activated_at = owner.activated_at or now
    await session.commit()
    return owner


FULL_NAME_MAX = 200


async def update_full_name(session: AsyncSession, user: User, full_name: str | None) -> None:
    """Keep the Telegram display name fresh (TZ 6.1: updated on every /start)."""
    name = (full_name or "").strip()[:FULL_NAME_MAX] or None
    if name is not None and user.full_name != name:
        user.full_name = name
        await session.commit()
