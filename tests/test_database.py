"""Database lifecycle regression tests."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from aestron_bot.database import DatabaseService


class _AcquireContext:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Pool:
    def __init__(self):
        self.connection = type("Connection", (), {})()
        self.connection.execute = AsyncMock()
        self.close = AsyncMock()
        self.closing = False

    def acquire(self):
        return _AcquireContext(self.connection)

    def is_closing(self):
        return self.closing


def test_pool_is_unavailable_before_connect():
    service = DatabaseService()
    assert service.connected is False
    with pytest.raises(RuntimeError, match="not connected"):
        _ = service.pool


def test_connect_validates_and_close_releases_pool(monkeypatch):
    async def run_test():
        pool = _Pool()
        create_pool = AsyncMock(return_value=pool)
        monkeypatch.setattr("aestron_bot.database.asyncpg.create_pool", create_pool)
        service = DatabaseService()

        await service.connect("postgresql://test", min_size=2, max_size=8)

        assert service.pool is pool
        create_pool.assert_awaited_once_with(
            "postgresql://test", min_size=2, max_size=8
        )
        pool.connection.execute.assert_awaited_once_with("SELECT 1")

        await service.close()
        pool.close.assert_awaited_once()
        assert service.connected is False

    asyncio.run(run_test())
