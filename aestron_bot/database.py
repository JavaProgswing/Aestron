"""PostgreSQL lifecycle management for Aestron."""

from __future__ import annotations

import logging

import asyncpg

LOGGER = logging.getLogger(__name__)


class DatabaseService:
    """Own the bot's asyncpg pool and make readiness explicit."""

    def __init__(self) -> None:
        """Create a disconnected database service."""
        self._pool: asyncpg.Pool | None = None

    @property
    def connected(self) -> bool:
        """Return whether the service currently owns an open pool."""
        return self._pool is not None and not self._pool.is_closing()

    @property
    def pool(self) -> asyncpg.Pool:
        """Return the ready pool or fail with an actionable lifecycle error."""
        if not self.connected or self._pool is None:
            raise RuntimeError("The PostgreSQL pool is not connected yet.")
        return self._pool

    async def connect(self, dsn: str, *, min_size: int = 1, max_size: int = 20) -> None:
        """Create the pool once and verify a connection before returning."""
        if self.connected:
            return
        LOGGER.info("Connecting PostgreSQL pool min=%s max=%s", min_size, max_size)
        pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
        try:
            async with pool.acquire() as connection:
                await connection.execute("SELECT 1")
        except Exception:
            await pool.close()
            raise
        self._pool = pool
        LOGGER.info("PostgreSQL pool is ready")

    async def close(self) -> None:
        """Close the owned pool safely and make the service disconnected."""
        pool, self._pool = self._pool, None
        if pool is not None:
            await pool.close()
            LOGGER.info("PostgreSQL pool closed")
