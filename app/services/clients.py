"""Clients: people the owner has debts with (TZ 10)."""

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, Operation, User
from app.domain.errors import DomainError, NotFound
from app.services.pagination import Page, paginate

NAME_MAX = 100
COMMENT_MAX = 1000
RECENT_LIMIT = 6


class InvalidClientName(DomainError):
    def __init__(self, too_long: bool) -> None:
        super().__init__("too long" if too_long else "empty")
        self.too_long = too_long


class CommentTooLong(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"longer than {limit}")
        self.limit = limit


class DuplicateClientName(DomainError):
    def __init__(self, existing_name: str) -> None:
        super().__init__(existing_name)
        self.existing_name = existing_name


class ClientHasOperations(DomainError):
    pass


class ClientNotFound(NotFound):
    pass


def normalize_name(raw: str) -> str:
    """Trim and collapse inner whitespace: '  Иван   Петров ' -> 'Иван Петров'."""
    name = " ".join(raw.split())
    if not name:
        raise InvalidClientName(too_long=False)
    if len(name) > NAME_MAX:
        raise InvalidClientName(too_long=True)
    return name


def normalize_comment(raw: str | None, limit: int) -> str | None:
    comment = (raw or "").strip()
    if not comment:
        return None
    if len(comment) > limit:
        raise CommentTooLong(limit)
    return comment


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def find_by_name(
    session: AsyncSession, name: str, exclude_id: int | None = None
) -> Client | None:
    statement = select(Client).where(func.lower(Client.name) == func.lower(name))
    if exclude_id is not None:
        statement = statement.where(Client.id != exclude_id)
    return await session.scalar(statement)


async def check_name_available(
    session: AsyncSession, raw_name: str, exclude_id: int | None = None
) -> str:
    """Normalize a name and make sure no other client has it (ignoring case)."""
    name = normalize_name(raw_name)
    existing = await find_by_name(session, name, exclude_id)
    if existing is not None:
        raise DuplicateClientName(existing.name)
    return name


async def get_client(session: AsyncSession, client_id: int) -> Client:
    client = await session.get(Client, client_id)
    if client is None:
        raise ClientNotFound(client_id)
    return client


async def _commit_name_change(session: AsyncSession, name: str) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        # Someone saved the same name between our check and the commit.
        await session.rollback()
        existing = await find_by_name(session, name)
        raise DuplicateClientName(existing.name if existing else name) from exc


async def create_client(
    session: AsyncSession, actor: User, raw_name: str, raw_comment: str | None = None
) -> Client:
    name = await check_name_available(session, raw_name)
    comment = normalize_comment(raw_comment, COMMENT_MAX)
    client = Client(name=name, comment=comment, created_by_id=actor.id)
    session.add(client)
    await _commit_name_change(session, name)
    return client


async def rename_client(session: AsyncSession, client_id: int, raw_name: str) -> Client:
    client = await get_client(session, client_id)
    name = await check_name_available(session, raw_name, exclude_id=client.id)
    client.name = name
    await _commit_name_change(session, name)
    return client


async def update_comment(session: AsyncSession, client_id: int, raw_comment: str | None) -> Client:
    client = await get_client(session, client_id)
    client.comment = normalize_comment(raw_comment, COMMENT_MAX)
    await session.commit()
    return client


async def has_operations(session: AsyncSession, client_id: int) -> bool:
    return bool(await session.scalar(select(exists().where(Operation.client_id == client_id))))


async def delete_client(session: AsyncSession, client_id: int) -> Client:
    """Only a client without any records can be deleted (TZ 10)."""
    client = await get_client(session, client_id)
    if await has_operations(session, client_id):
        raise ClientHasOperations(client_id)
    await session.delete(client)
    try:
        await session.commit()
    except IntegrityError as exc:
        # A record for this client was saved in the meantime (FK ... ON DELETE RESTRICT).
        await session.rollback()
        raise ClientHasOperations(client_id) from exc
    return client


async def list_clients(session: AsyncSession, page: int) -> Page[Client]:
    statement = select(Client).order_by(func.lower(Client.name), Client.id)
    return await paginate(session, statement, page)


def normalize_query(raw: str) -> str:
    return " ".join(raw.split())


async def search_clients(session: AsyncSession, raw_query: str, page: int) -> Page[Client]:
    """Substring search ignoring case (ILIKE '%...%')."""
    query = normalize_query(raw_query)
    statement = (
        select(Client)
        .where(Client.name.ilike(f"%{_escape_like(query)}%", escape="\\"))
        .order_by(func.lower(Client.name), Client.id)
    )
    return await paginate(session, statement, page)


async def recent_clients(session: AsyncSession, limit: int = RECENT_LIMIT) -> list[Client]:
    """Latest activity first: last record time, or creation time for clients without records."""
    last_operation = (
        select(Operation.client_id, func.max(Operation.created_at).label("last_at"))
        .group_by(Operation.client_id)
        .subquery()
    )
    statement = (
        select(Client)
        .outerjoin(last_operation, last_operation.c.client_id == Client.id)
        .order_by(
            func.coalesce(last_operation.c.last_at, Client.created_at).desc(), Client.id.desc()
        )
        .limit(limit)
    )
    return list(await session.scalars(statement))
