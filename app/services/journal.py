"""Lists of records: «Записи дня» (TZ 13.7) and the history of a client (TZ 13.6)."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Row, Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import Client, Operation
from app.services.pagination import Page, paginate


@dataclass(frozen=True)
class RecordRow:
    operation: Operation
    client_name: str | None
    reversed_by: int | None  # the record that cancelled this one


def _rows() -> Select[Any]:
    reversal = aliased(Operation)
    return (
        select(Operation, Client.name, reversal.id)
        .outerjoin(Client, Client.id == Operation.client_id)
        .outerjoin(reversal, reversal.reversal_of_id == Operation.id)
        .order_by(Operation.id.desc())
    )


def _row(row: Row[Any]) -> RecordRow:
    operation, client_name, reversed_by = row
    return RecordRow(operation, client_name, reversed_by)


async def day_records(session: AsyncSession, day_id: int, page: int) -> Page[RecordRow]:
    """Records of a day, the newest first."""
    statement = _rows().where(Operation.day_id == day_id)
    return await paginate(session, statement, page, row_mapper=_row)


async def client_records(session: AsyncSession, client_id: int, page: int) -> Page[RecordRow]:
    """Records of a client over all days, the newest first."""
    statement = _rows().where(Operation.client_id == client_id)
    return await paginate(session, statement, page, row_mapper=_row)
