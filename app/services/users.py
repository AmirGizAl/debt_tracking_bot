import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole, UserStatus
from app.domain.errors import DomainError, NotFound, PermissionDenied

USERNAME_RE = re.compile(r"^[a-z0-9_]{5,32}$")
FULL_NAME_MAX = 200


class InvalidUsername(DomainError):
    pass


class UsernameAlreadyAdded(DomainError):
    pass


class CannotDeleteOwner(DomainError):
    pass


class UserNotFound(NotFound):
    pass


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
