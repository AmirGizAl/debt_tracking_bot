import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole, UserStatus
from app.domain.errors import PermissionDenied
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


# --- helpers (TZ 9.2-9.4) --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@Aigul_K", "aigul_k"),
        ("  @aigul_k  ", "aigul_k"),
        ("@ aigul_k", "aigul_k"),
        ("AIGUL", "aigul"),
        ("a" * 32, "a" * 32),
    ],
)
def test_normalize_username(raw: str, expected: str) -> None:
    assert users.normalize_username(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "@", "aig", "a" * 33, "aigul k", "айгуль_k", "@@aigul_k", "aigul-k", "aigul.k"]
)
def test_normalize_username_rejects_invalid(raw: str) -> None:
    with pytest.raises(users.InvalidUsername):
        users.normalize_username(raw)


async def test_add_helper_creates_pending_user(session: AsyncSession, owner: User) -> None:
    helper = await users.add_helper(session, owner, "@Aigul_K")

    assert helper.username == "aigul_k"
    assert helper.role == UserRole.HELPER
    assert helper.status == UserStatus.PENDING
    assert helper.telegram_id is None
    assert helper.added_by_id == owner.id


async def test_add_helper_rejects_duplicate_ignoring_case(
    session: AsyncSession, owner: User
) -> None:
    await users.add_helper(session, owner, "aigul_k")

    with pytest.raises(users.UsernameAlreadyAdded):
        await users.add_helper(session, owner, "@AIGUL_K")


async def test_activation_matches_username_ignoring_case(
    session: AsyncSession, owner: User
) -> None:
    await users.add_helper(session, owner, "aigul_k")

    helper = await users.activate_by_username(session, 2002, "Aigul_K", "Айгуль")

    assert helper is not None
    assert helper.status == UserStatus.ACTIVE
    assert helper.telegram_id == 2002
    assert helper.full_name == "Айгуль"
    assert helper.activated_at is not None
    assert await users.get_active_by_telegram_id(session, 2002) == helper


@pytest.mark.parametrize("username", [None, "", "someone_else"])
async def test_activation_needs_matching_username(
    session: AsyncSession, owner: User, username: str | None
) -> None:
    await users.add_helper(session, owner, "aigul_k")

    assert await users.activate_by_username(session, 2002, username, "Айгуль") is None


async def test_deleted_helper_loses_access(session: AsyncSession, owner: User) -> None:
    await users.add_helper(session, owner, "aigul_k")
    helper = await users.activate_by_username(session, 2002, "aigul_k", "Айгуль")
    assert helper is not None

    deleted = await users.delete_helper(session, owner, helper.id)

    assert deleted.status == UserStatus.DELETED
    assert deleted.deleted_at is not None
    assert await users.get_active_by_telegram_id(session, 2002) is None
    # A deleted helper cannot re-activate by just writing to the bot again.
    assert await users.activate_by_username(session, 2002, "aigul_k", "Айгуль") is None


async def test_pending_helper_can_be_deleted(session: AsyncSession, owner: User) -> None:
    helper = await users.add_helper(session, owner, "aigul_k")

    await users.delete_helper(session, owner, helper.id)

    assert helper.status == UserStatus.DELETED


async def test_re_adding_deleted_helper_restores_the_same_row(
    session: AsyncSession, owner: User
) -> None:
    helper = await users.add_helper(session, owner, "aigul_k")
    await users.activate_by_username(session, 2002, "aigul_k", "Айгуль")
    await users.delete_helper(session, owner, helper.id)

    again = await users.add_helper(session, owner, "@aigul_k")

    assert again.id == helper.id
    assert again.status == UserStatus.PENDING
    assert again.telegram_id is None
    assert again.deleted_at is None
    # The same person (or a new account with this username) can activate again.
    reactivated = await users.activate_by_username(session, 3003, "aigul_k", "Айгуль")
    assert reactivated is not None
    assert reactivated.id == helper.id
    assert reactivated.telegram_id == 3003


async def test_owner_cannot_be_deleted(session: AsyncSession, owner: User) -> None:
    with pytest.raises(users.CannotDeleteOwner):
        await users.delete_helper(session, owner, owner.id)


async def test_list_helpers_hides_deleted(session: AsyncSession, owner: User) -> None:
    active = await users.add_helper(session, owner, "aigul_k")
    await users.activate_by_username(session, 2002, "aigul_k", "Айгуль")
    pending = await users.add_helper(session, owner, "bekzat_b")
    gone = await users.add_helper(session, owner, "timur_t")
    await users.delete_helper(session, owner, gone.id)

    assert await users.list_helpers(session, owner) == [active, pending]


async def test_helper_cannot_manage_helpers(session: AsyncSession, helper: User) -> None:
    with pytest.raises(PermissionDenied):
        await users.add_helper(session, helper, "bekzat_b")
    with pytest.raises(PermissionDenied):
        await users.list_helpers(session, helper)
    with pytest.raises(PermissionDenied):
        await users.delete_helper(session, helper, helper.id)
