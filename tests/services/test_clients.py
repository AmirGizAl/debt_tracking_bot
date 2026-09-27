from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, User
from app.domain import errors
from app.domain.currency import Currency
from app.domain.operations import OperationType
from app.services import balances, clients
from tests.factories import make_client, make_operation


def test_normalize_name_trims_and_collapses_spaces() -> None:
    assert clients.normalize_name("  Иван \t  Петров\n ") == "Иван Петров"


@pytest.mark.parametrize(("raw", "too_long"), [("   ", False), ("", False), ("я" * 101, True)])
def test_normalize_name_rejects(raw: str, too_long: bool) -> None:
    with pytest.raises(errors.InvalidClientName) as error:
        clients.normalize_name(raw)
    assert error.value.too_long is too_long


def test_name_of_100_characters_is_fine() -> None:
    assert clients.normalize_name("я" * 100) == "я" * 100


async def test_create_client(session: AsyncSession, owner: User) -> None:
    client = await clients.create_client(session, owner, " Иван ", " сосед, г. Бишкек ")

    assert client.name == "Иван"
    assert client.comment == "сосед, г. Бишкек"
    assert client.created_by_id == owner.id


@pytest.mark.parametrize("duplicate", ["иван", "ИВАН", "  Иван  ", "иВаН"])
async def test_duplicate_name_is_rejected_ignoring_case(
    session: AsyncSession, owner: User, duplicate: str
) -> None:
    await clients.create_client(session, owner, "Иван")

    with pytest.raises(errors.DuplicateClientName) as error:
        await clients.create_client(session, owner, duplicate)
    assert error.value.existing_name == "Иван"


async def test_rename_checks_uniqueness_but_allows_own_case_change(
    session: AsyncSession, owner: User
) -> None:
    ivan = await clients.create_client(session, owner, "Иван")
    await clients.create_client(session, owner, "Азамат")

    with pytest.raises(errors.DuplicateClientName):
        await clients.rename_client(session, ivan.id, "азамат")
    renamed = await clients.rename_client(session, ivan.id, "ИВАН")
    assert renamed.name == "ИВАН"


async def test_comment_limits(session: AsyncSession, owner: User) -> None:
    client = await clients.create_client(session, owner, "Иван", "я" * 1000)
    assert client.comment == "я" * 1000

    with pytest.raises(errors.TextTooLong):
        await clients.update_comment(session, client.id, "я" * 1001)
    cleared = await clients.update_comment(session, client.id, "   ")
    assert cleared.comment is None


async def test_client_without_operations_can_be_deleted(session: AsyncSession, owner: User) -> None:
    client = await clients.create_client(session, owner, "Иван")

    await clients.delete_client(session, client.id)

    assert await session.scalar(select(Client).where(Client.id == client.id)) is None


async def test_client_with_operations_cannot_be_deleted(session: AsyncSession, owner: User) -> None:
    client = await clients.create_client(session, owner, "Иван")
    await make_operation(session, owner, client, OperationType.LEND, "100")

    assert await clients.has_operations(session, client.id)
    with pytest.raises(errors.ClientHasOperations):
        await clients.delete_client(session, client.id)


async def test_search_is_case_insensitive_substring(session: AsyncSession, owner: User) -> None:
    for name in ("Иван", "Иван (Ош)", "Бекзат", "Сыйнат Иванова"):
        await clients.create_client(session, owner, name)

    page = await clients.search_clients(session, "  иВ ", 0)

    assert [c.name for c in page.items] == ["Иван", "Иван (Ош)", "Сыйнат Иванова"]


async def test_search_treats_like_wildcards_literally(session: AsyncSession, owner: User) -> None:
    for name in ("Скидка 100%", "Иван_Ош", "Бекзат"):
        await clients.create_client(session, owner, name)

    assert [c.name for c in (await clients.search_clients(session, "%", 0)).items] == [
        "Скидка 100%"
    ]
    assert [c.name for c in (await clients.search_clients(session, "_", 0)).items] == ["Иван_Ош"]


async def test_list_is_alphabetical_and_paginated(session: AsyncSession, owner: User) -> None:
    names = [f"Клиент {n:02d}" for n in range(12, 0, -1)] + ["азамат"]
    for name in names:
        await clients.create_client(session, owner, name)

    first = await clients.list_clients(session, 0)
    last = await clients.list_clients(session, 99)

    assert first.total == 13
    assert first.pages == 2
    assert [c.name for c in first.items][:3] == ["азамат", "Клиент 01", "Клиент 02"]
    assert last.page == 1
    assert [c.name for c in last.items] == ["Клиент 10", "Клиент 11", "Клиент 12"]


async def test_recent_clients_by_last_activity(session: AsyncSession, owner: User) -> None:
    base = datetime(2026, 9, 1, tzinfo=UTC)
    old_debtor = await make_client(session, owner, "Старый", created_at=base)
    fresh_debtor = await make_client(session, owner, "Свежий", created_at=base)
    just_created = await make_client(session, owner, "Новый", created_at=base + timedelta(days=5))
    for number in range(4):
        await make_client(session, owner, f"Давний {number}", created_at=base - timedelta(days=9))
    await make_operation(
        session, owner, old_debtor, OperationType.LEND, "1", created_at=base + timedelta(days=1)
    )
    await make_operation(
        session, owner, fresh_debtor, OperationType.LEND, "1", created_at=base + timedelta(days=9)
    )

    recent = await clients.recent_clients(session)

    assert [c.name for c in recent[:3]] == [fresh_debtor.name, just_created.name, old_debtor.name]
    assert len(recent) == 6


async def test_client_balances_sum_the_journal(session: AsyncSession, owner: User) -> None:
    ivan = await make_client(session, owner, "Иван")
    await make_operation(session, owner, ivan, OperationType.LEND, "1000")
    await make_operation(session, owner, ivan, OperationType.BORROW, "300")
    await make_operation(session, owner, ivan, OperationType.BORROW, "20000", Currency.RUB)

    result = await balances.client_balances(session, ivan.id)

    assert result[Currency.USD] == 700
    assert result[Currency.RUB] == -20000
    assert result[Currency.KGS] == 0
    assert list(result) == list(Currency)
