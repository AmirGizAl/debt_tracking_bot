import re
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole, UserStatus
from app.domain.errors import (
    CannotDeleteOwner,
    InvalidUsername,
    PermissionDenied,
    UsernameAlreadyAdded,
    UserNotFound,
)

USERNAME_RE = re.compile(r"^[a-z0-9_]{5,32}$")
FULL_NAME_MAX = 200


def _now() -> datetime:
    return datetime.now(UTC)


def _clip_full_name(full_name: str | None) -> str | None:
    return (full_name or "").strip()[:FULL_NAME_MAX] or None


def normalize_username(raw: str) -> str:
    """'  @Aigul_K ' -> 'aigul_k' (TZ 9.2). Raises InvalidUsername."""
    username = raw.strip().removeprefix("@").strip().lower()
    if not USERNAME_RE.fullmatch(username):
        raise InvalidUsername(raw)
    return username


def require_owner(actor: User) -> None:
    if not (actor.is_owner and actor.is_active):
        raise PermissionDenied("owner only")


async def get_active_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(
        select(User).where(User.telegram_id == telegram_id, User.status == UserStatus.ACTIVE)
    )


async def ensure_owner(session: AsyncSession, telegram_id: int) -> User:
    """Make the account an active owner; does not commit.

    A helper with this account becomes an owner (TZ 13.12). A removed owner or helper coming
    back gets their old row again, so their records stay theirs.
    """
    now = _now()
    user = await session.scalar(
        select(User).where(User.telegram_id == telegram_id, User.status != UserStatus.DELETED)
    )
    if user is None:
        user = await session.scalar(
            select(User)
            .where(User.telegram_id == telegram_id, User.status == UserStatus.DELETED)
            .order_by(User.id.desc())
            .limit(1)
        )
        if user is not None and user.username is not None:
            taken = await session.scalar(
                select(User.id).where(
                    User.username == user.username, User.status != UserStatus.DELETED
                )
            )
            if taken is not None:
                # The nickname now belongs to someone invited later; owners do without it.
                user.username = None
    if user is None:
        user = User(telegram_id=telegram_id, role=UserRole.OWNER, status=UserStatus.ACTIVE)
        session.add(user)
    user.role = UserRole.OWNER
    if user.status != UserStatus.ACTIVE:
        user.status = UserStatus.ACTIVE
        user.activated_at = now
        user.deleted_at = None
    user.activated_at = user.activated_at or now
    await session.flush()
    return user


async def sync_owners(session: AsyncSession, telegram_ids: Sequence[int]) -> list[User]:
    """Owners are exactly the accounts of OWNER_TELEGRAM_IDS (TZ 13.12), run on every start.

    An owner who is no longer listed is marked deleted: access is gone at once, their records
    stay in history as "(удалён)".
    """
    if not telegram_ids:
        raise ValueError("the list of owners is empty")
    now = _now()
    removed = await session.scalars(
        select(User).where(
            User.role == UserRole.OWNER,
            User.status != UserStatus.DELETED,
            or_(User.telegram_id.is_(None), User.telegram_id.not_in(telegram_ids)),
        )
    )
    for user in removed:
        user.status = UserStatus.DELETED
        user.deleted_at = now
    await session.flush()
    owners = [await ensure_owner(session, telegram_id) for telegram_id in telegram_ids]
    await session.commit()
    return owners


async def active_owners(session: AsyncSession) -> list[User]:
    """Everybody who gets the owners' notifications (TZ 13.11)."""
    result = await session.scalars(
        select(User)
        .where(
            User.role == UserRole.OWNER,
            User.status == UserStatus.ACTIVE,
            User.telegram_id.is_not(None),
        )
        .order_by(User.id)
    )
    return list(result)


async def update_full_name(session: AsyncSession, user: User, full_name: str | None) -> None:
    """Keep the Telegram display name fresh (TZ 6.1: updated on every /start)."""
    name = _clip_full_name(full_name)
    if name is not None and user.full_name != name:
        user.full_name = name
        await session.commit()


async def add_helper(session: AsyncSession, actor: User, raw_username: str) -> User:
    """Invite a helper by Telegram username (TZ 9.2)."""
    require_owner(actor)
    username = normalize_username(raw_username)
    taken = await session.scalar(
        select(User.id).where(User.username == username, User.status != UserStatus.DELETED)
    )
    if taken is not None:
        raise UsernameAlreadyAdded(username)

    helper = await session.scalar(
        select(User)
        .where(User.username == username, User.status == UserStatus.DELETED)
        .order_by(User.id.desc())
        .limit(1)
    )
    if helper is None:
        helper = User(username=username)
        session.add(helper)
    # A removed helper comes back as the same row: their old records stay theirs.
    helper.role = UserRole.HELPER
    helper.status = UserStatus.PENDING
    helper.telegram_id = None
    helper.added_by_id = actor.id
    helper.activated_at = None
    helper.deleted_at = None
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise UsernameAlreadyAdded(username) from exc
    return helper


async def activate_by_username(
    session: AsyncSession, telegram_id: int, username: str | None, full_name: str | None
) -> User | None:
    """Turn a pending helper into an active one on their first update (TZ 9.3)."""
    if not username:
        return None
    helper = await session.scalar(
        select(User).where(
            User.username == username.lower(),
            User.status == UserStatus.PENDING,
        )
    )
    if helper is None:
        return None
    helper.telegram_id = telegram_id
    helper.full_name = _clip_full_name(full_name) or helper.full_name
    helper.status = UserStatus.ACTIVE
    helper.activated_at = _now()
    try:
        await session.commit()
    except IntegrityError:
        # This Telegram account already belongs to another live user.
        await session.rollback()
        return None
    return helper


async def list_helpers(session: AsyncSession, actor: User) -> list[User]:
    require_owner(actor)
    result = await session.scalars(
        select(User)
        .where(User.role == UserRole.HELPER, User.status != UserStatus.DELETED)
        .order_by(User.created_at, User.id)
    )
    return list(result)


async def get_helper(session: AsyncSession, actor: User, helper_id: int) -> User:
    require_owner(actor)
    helper = await session.get(User, helper_id)
    if helper is None or helper.role != UserRole.HELPER or helper.status == UserStatus.DELETED:
        raise UserNotFound(helper_id)
    return helper


async def delete_helper(session: AsyncSession, actor: User, helper_id: int) -> User:
    """Soft-delete a helper: access is gone at once, records stay (TZ 9.4)."""
    require_owner(actor)
    helper = await session.get(User, helper_id)
    if helper is None or helper.status == UserStatus.DELETED:
        raise UserNotFound(helper_id)
    if helper.is_owner:
        raise CannotDeleteOwner(helper_id)
    helper.status = UserStatus.DELETED
    helper.deleted_at = _now()
    await session.commit()
    return helper
