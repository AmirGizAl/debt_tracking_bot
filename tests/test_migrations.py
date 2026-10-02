"""Upgrade of a version 1 database with data (TZ 16.4): users and clients stay, records go."""

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import _alembic

V1_ROWS = [
    "INSERT INTO users (id, telegram_id, username, role, status)"
    " VALUES (1, 1001, NULL, 'owner', 'active'), (2, 2002, 'aigul_k', 'helper', 'active')",
    "INSERT INTO clients (id, name, comment, created_by_id) VALUES (1, 'Азамат', 'сосед', 1)",
    "INSERT INTO operations (request_id, type, client_id, debt_currency, debt_amount,"
    " cash_currency, cash_amount, debt_delta, cash_delta, op_date, author_id)"
    " VALUES (gen_random_uuid(), 'lend', 1, 'USD', 100, 'USD', 100, 100, -100,"
    " '2026-09-28', 1)",
    "INSERT INTO cash_adjustments (request_id, currency, amount, reason, adj_date, author_id)"
    " VALUES (gen_random_uuid(), 'USD', 1000, 'Остаток на начало работы', '2026-09-28', 1)",
]


async def scalar(engine: AsyncEngine, sql: str) -> object:
    async with engine.connect() as connection:
        return (await connection.execute(text(sql))).scalar_one()


async def test_upgrade_keeps_users_and_clients_and_drops_v1_records(
    migrated_engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    async with migrated_engine.begin() as connection:
        await connection.run_sync(_alembic, "downgrade", "0001")
    try:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE users, clients, operations, cash_adjustments RESTART IDENTITY CASCADE"
                )
            )
            for statement in V1_ROWS:
                await connection.execute(text(statement))

        with caplog.at_level(logging.WARNING, logger="alembic.runtime.migration"):
            async with migrated_engine.begin() as connection:
                await connection.run_sync(_alembic, "upgrade", "head")

        assert await scalar(migrated_engine, "SELECT count(*) FROM users") == 2
        assert await scalar(migrated_engine, "SELECT name FROM clients") == "Азамат"
        assert await scalar(migrated_engine, "SELECT count(*) FROM operations") == 0
        assert await scalar(migrated_engine, "SELECT count(*) FROM business_days") == 0
        assert (
            await scalar(migrated_engine, "SELECT enum_range(NULL::currency)::text")
            == "{USD,EUR,RUB,KZT,KGS}"
        )
        assert "Dropping 1 rows of operations (version 1)" in caplog.text
        assert "Dropping 1 rows of cash_adjustments (version 1)" in caplog.text
    finally:
        async with migrated_engine.begin() as connection:
            await connection.run_sync(_alembic, "upgrade", "head")
