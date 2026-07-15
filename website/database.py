"""PostgreSQL persistence for linked Riot accounts and product feedback."""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from .models import FeedbackCreate

LOGGER = logging.getLogger(__name__)


class DatabaseUnavailableError(RuntimeError):
    """Raised when a persistence-dependent feature is used without PostgreSQL."""


class WebsiteDatabase:
    """Own the website's asynchronous PostgreSQL pool and queries."""

    def __init__(self, dsn: str | None) -> None:
        """Create a disconnected database wrapper for an optional DSN."""
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None
        self.last_error: str | None = None

    @property
    def connected(self) -> bool:
        """Whether the website currently has a live database pool."""
        return self.pool is not None

    async def connect(self) -> None:
        """Connect and create backward-compatible web tables and columns."""
        if not self.dsn:
            self.last_error = "AESTRON_DATABASE_DSN is not configured."
            LOGGER.warning("Website persistence disabled: %s", self.last_error)
            return
        try:
            pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)
            async with pool.acquire() as connection:
                await self._ensure_schema(connection)
        except Exception as error:
            self.last_error = f"{type(error).__name__}: {error}"
            LOGGER.exception("Website database initialization failed")
            return
        self.pool = pool
        self.last_error = None

    async def close(self) -> None:
        """Close the website database pool."""
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def create_feedback(
        self, feedback: FeedbackCreate, *, source: str
    ) -> dict[str, Any]:
        """Persist one validated suggestion or bug report."""
        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO aestron_feedback
                    (kind, title, body, contact, discord_user_id, source)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
                """,
                feedback.kind,
                feedback.title,
                feedback.body,
                feedback.contact,
                feedback.discord_user_id,
                source,
            )
        return dict(row)

    async def list_feedback(self, *, status: str | None, limit: int) -> list[dict]:
        """Return recent feedback for the administrative dashboard."""
        pool = self._require_pool()
        async with pool.acquire() as connection:
            if status:
                rows = await connection.fetch(
                    """
                    SELECT * FROM aestron_feedback
                    WHERE status = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    status,
                    limit,
                )
            else:
                rows = await connection.fetch(
                    """
                    SELECT * FROM aestron_feedback
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
        return [dict(row) for row in rows]

    async def update_feedback_status(
        self, feedback_id: int, new_status: str
    ) -> dict[str, Any] | None:
        """Update one feedback item and return its current representation."""
        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE aestron_feedback
                SET status = $1, updated_at = NOW()
                WHERE id = $2
                RETURNING *
                """,
                new_status,
                feedback_id,
            )
        return dict(row) if row else None

    async def feedback_counts(self) -> dict[str, int]:
        """Count feedback by workflow status."""
        pool = self._require_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT status, COUNT(*) AS count FROM aestron_feedback GROUP BY status"
            )
        return {row["status"]: row["count"] for row in rows}

    async def upsert_riot_account(
        self,
        *,
        discord_user_id: int,
        puuid: str,
        game_name: str,
        tag_line: str,
        region: str,
    ) -> None:
        """Store an explicitly opted-in Riot identity without OAuth tokens."""
        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO riotaccount
                    (discorduserid, accountpuuid, accountname, accounttag,
                     accountregion, opted_in_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
                ON CONFLICT (discorduserid) DO UPDATE
                SET accountpuuid = EXCLUDED.accountpuuid,
                    accountname = EXCLUDED.accountname,
                    accounttag = EXCLUDED.accounttag,
                    accountregion = EXCLUDED.accountregion,
                    opted_in_at = NOW(),
                    updated_at = NOW()
                """,
                discord_user_id,
                puuid,
                game_name,
                tag_line,
                region,
            )

    async def get_riot_account(self, discord_user_id: int) -> dict[str, Any] | None:
        """Return the linked account visible to the authenticated bot service."""
        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT discorduserid, accountpuuid, accountname, accounttag,
                       accountregion, opted_in_at, updated_at
                FROM riotaccount
                WHERE discorduserid = $1
                """,
                discord_user_id,
            )
        return dict(row) if row else None

    async def delete_riot_account(self, discord_user_id: int) -> bool:
        """Delete an account link and its cached match references."""
        pool = self._require_pool()
        async with pool.acquire() as connection:
            result = await connection.execute(
                "DELETE FROM riotaccount WHERE discorduserid = $1",
                discord_user_id,
            )
        return result.endswith("1")

    def _require_pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise DatabaseUnavailableError(
                self.last_error or "The database is currently unavailable."
            )
        return self.pool

    @staticmethod
    async def _ensure_schema(connection: asyncpg.Connection) -> None:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS aestron_feedback (
                id BIGSERIAL PRIMARY KEY,
                kind TEXT NOT NULL CHECK (kind IN ('suggestion', 'bug')),
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                contact TEXT,
                discord_user_id BIGINT,
                source TEXT NOT NULL DEFAULT 'website',
                status TEXT NOT NULL DEFAULT 'new'
                    CHECK (status IN
                        ('new', 'reviewing', 'planned', 'resolved', 'rejected')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS riotaccount (
                discorduserid BIGINT PRIMARY KEY,
                accountpuuid TEXT NOT NULL,
                accountname TEXT NOT NULL,
                accounttag TEXT NOT NULL,
                accountimage TEXT,
                accountregion TEXT,
                opted_in_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await connection.execute(
            "ALTER TABLE riotaccount ADD COLUMN IF NOT EXISTS accountregion TEXT"
        )
        await connection.execute(
            "ALTER TABLE riotaccount ADD COLUMN IF NOT EXISTS opted_in_at TIMESTAMPTZ"
        )
        await connection.execute(
            """
            ALTER TABLE riotaccount
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            """
        )
