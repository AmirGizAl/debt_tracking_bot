from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def isolated(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """A short separate transaction on its own connection.

    Commits on success, rolls back on any exception. Its rollback cannot expire the objects
    of the caller's session (the handler keeps using `user` after "not enough cash"), and an
    advisory lock taken inside lives exactly as long as this transaction.
    Objects returned from it are detached but keep their loaded attributes.
    """
    transaction = AsyncSession(session.bind, expire_on_commit=False)
    async with transaction, transaction.begin():
        yield transaction
