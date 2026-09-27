from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

PAGE_SIZE = 10  # TZ 11: long lists are shown 10 items per page


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    page: int  # zero-based
    total: int
    page_size: int = PAGE_SIZE

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))

    @property
    def has_prev(self) -> bool:
        return self.page > 0

    @property
    def has_next(self) -> bool:
        return self.page + 1 < self.pages


async def paginate(
    session: AsyncSession, statement: Select[Any], page: int, page_size: int = PAGE_SIZE
) -> Page[Any]:
    """Run an ordered SELECT of one entity for one page; a page past the end shows the last."""
    total = await session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    pages = max(1, -(-total // page_size))
    page = min(max(page, 0), pages - 1)
    result = await session.scalars(statement.offset(page * page_size).limit(page_size))
    return Page(items=list(result), page=page, total=total, page_size=page_size)
