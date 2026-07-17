"""Batched, privacy-preserving guild activity aggregation and reporting."""

from __future__ import annotations

import asyncio
import contextlib
import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO, StringIO

import discord
from discord.ext import commands

LOGGER = logging.getLogger(__name__)
ACTIVITY_FLUSH_SECONDS = 30.0


@dataclass(slots=True)
class ActivityDelta:
    """One guild's unflushed aggregate activity."""

    messages: int = 0
    commands: int = 0
    last_message_at: datetime | None = None
    last_command_at: datetime | None = None


def _spreadsheet_safe(value: str) -> str:
    """Prevent guild names from becoming formulas in an exported CSV."""
    return "'" + value if value.startswith(("=", "+", "-", "@")) else value


class GuildActivityTracker:
    """Aggregate guild activity without retaining content, authors, or channels."""

    def __init__(self, bot: commands.Bot) -> None:
        """Create an empty batch and background worker state."""
        self.bot = bot
        self.pending: dict[int, ActivityDelta] = {}
        self._flush_task: asyncio.Task[None] | None = None
        self._closed = False

    async def start(self) -> None:
        """Create persistence and start the periodic batch flush."""
        if not self.bot.database.connected:
            return
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS aestron_guild_activity (
                    guild_id BIGINT PRIMARY KEY,
                    message_count BIGINT NOT NULL DEFAULT 0,
                    command_count BIGINT NOT NULL DEFAULT 0,
                    last_message_at TIMESTAMPTZ,
                    last_command_at TIMESTAMPTZ,
                    last_active_at TIMESTAMPTZ,
                    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        self._flush_task = asyncio.create_task(
            self._flush_loop(),
            name="aestron-guild-activity-flush",
        )

    async def close(self) -> None:
        """Stop the worker and persist its final batch once."""
        if self._closed:
            return
        self._closed = True
        if self._flush_task is not None:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None
        await self.flush()

    def record(self, guild_id: int, *, command: bool) -> None:
        """Record a timestamp and count without database I/O."""
        delta = self.pending.setdefault(guild_id, ActivityDelta())
        now = discord.utils.utcnow()
        if command:
            delta.commands += 1
            delta.last_command_at = now
        else:
            delta.messages += 1
            delta.last_message_at = now

    async def flush(self) -> None:
        """Persist pending aggregates in one bounded database operation."""
        if not self.pending or not self.bot.database.connected:
            return
        pending, self.pending = self.pending, {}
        rows = [
            (
                guild_id,
                delta.messages,
                delta.commands,
                delta.last_message_at,
                delta.last_command_at,
            )
            for guild_id, delta in pending.items()
        ]
        try:
            async with self.bot.database.pool.acquire() as connection:
                await connection.executemany(
                    """
                    INSERT INTO aestron_guild_activity
                        (guild_id, message_count, command_count,
                         last_message_at, last_command_at, last_active_at)
                    VALUES ($1, $2, $3, $4, $5, GREATEST($4, $5))
                    ON CONFLICT (guild_id) DO UPDATE SET
                        message_count = aestron_guild_activity.message_count
                            + EXCLUDED.message_count,
                        command_count = aestron_guild_activity.command_count
                            + EXCLUDED.command_count,
                        last_message_at = GREATEST(
                            aestron_guild_activity.last_message_at,
                            EXCLUDED.last_message_at
                        ),
                        last_command_at = GREATEST(
                            aestron_guild_activity.last_command_at,
                            EXCLUDED.last_command_at
                        ),
                        last_active_at = GREATEST(
                            aestron_guild_activity.last_active_at,
                            EXCLUDED.last_active_at
                        ),
                        updated_at = NOW()
                    """,
                    rows,
                )
        except asyncio.CancelledError:
            self._restore(pending)
            raise
        except Exception:
            self._restore(pending)
            LOGGER.exception("Could not flush guild activity; batch will be retried")

    def _restore(self, pending: dict[int, ActivityDelta]) -> None:
        """Merge a failed flush back into activity recorded meanwhile."""
        for guild_id, failed in pending.items():
            current = self.pending.setdefault(guild_id, ActivityDelta())
            current.messages += failed.messages
            current.commands += failed.commands
            if failed.last_message_at and (
                current.last_message_at is None
                or failed.last_message_at > current.last_message_at
            ):
                current.last_message_at = failed.last_message_at
            if failed.last_command_at and (
                current.last_command_at is None
                or failed.last_command_at > current.last_command_at
            ):
                current.last_command_at = failed.last_command_at

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(ACTIVITY_FLUSH_SECONDS)
            await self.flush()

    async def report(
        self,
        window: timedelta,
        window_label: str,
    ) -> tuple[discord.Embed, discord.File]:
        """Build a private summary and complete CSV for every current guild."""
        await self.flush()
        async with self.bot.database.pool.acquire() as connection:
            activity_rows = await connection.fetch(
                "SELECT * FROM aestron_guild_activity"
            )
            subscription_rows = await connection.fetch(
                "SELECT guild_id, channel_id, enabled FROM guild_update_subscriptions"
            )
        activity = {int(row["guild_id"]): row for row in activity_rows}
        subscriptions = {int(row["guild_id"]): row for row in subscription_rows}
        now = discord.utils.utcnow()
        active_now = 0
        active_window = 0
        subscribed = 0
        report_rows = []
        ranked = []
        for guild in self.bot.guilds:
            row = activity.get(guild.id)
            last_active = row["last_active_at"] if row is not None else None
            age = now - last_active if last_active is not None else None
            if age is not None and age <= timedelta(minutes=15):
                label = "active_now"
                active_now += 1
                active_window += 1
            elif age is not None and age <= window:
                label = "active"
                active_window += 1
            elif age is not None:
                label = "quiet"
            else:
                label = "no_data"
            subscription = subscriptions.get(guild.id)
            is_subscribed = bool(subscription and subscription["enabled"])
            subscribed += int(is_subscribed)
            last_command = row["last_command_at"] if row is not None else None
            messages = int(row["message_count"]) if row is not None else 0
            commands_used = int(row["command_count"]) if row is not None else 0
            report_rows.append(
                (
                    guild.id,
                    guild.name,
                    guild.member_count or 0,
                    label,
                    last_active,
                    last_command,
                    messages,
                    commands_used,
                    is_subscribed,
                    int(subscription["channel_id"]) if is_subscribed else "",
                )
            )
            ranked.append((last_active, guild))

        ranked.sort(
            key=lambda item: item[0] or discord.utils.snowflake_time(0),
            reverse=True,
        )
        lines = [
            f"**{guild.name[:40]}** (`{guild.id}`) — "
            + (
                discord.utils.format_dt(last_active, "R")
                if last_active is not None
                else "No activity recorded"
            )
            for last_active, guild in ranked[:10]
        ]
        embed = discord.Embed(
            title="Guild activity overview",
            description=(
                "Activity means a human message or completed/recognized command. "
                "Only aggregate counts and timestamps are stored."
            ),
            color=0x5865F2,
            timestamp=now,
        )
        embed.add_field(name="Current guilds", value=f"{len(self.bot.guilds):,}")
        embed.add_field(name="Active ≤15m", value=f"{active_now:,}")
        embed.add_field(name=f"Active ≤{window_label}", value=f"{active_window:,}")
        embed.add_field(name="Update subscribers", value=f"{subscribed:,}")
        embed.add_field(
            name="Most recently active",
            value="\n".join(lines)[:1024] or "No activity recorded yet.",
            inline=False,
        )
        embed.set_footer(text="CSV counts are lifetime totals since tracking began")
        return embed, self._csv(report_rows)

    @staticmethod
    def _csv(rows: list[tuple]) -> discord.File:
        """Serialize the complete activity inventory for private download."""
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            (
                "guild_id",
                "guild_name",
                "member_count",
                "activity_status",
                "last_active_at",
                "last_command_at",
                "messages_tracked",
                "commands_tracked",
                "updates_subscribed",
                "update_channel_id",
            )
        )
        for row in rows:
            writer.writerow(
                (
                    row[0],
                    _spreadsheet_safe(row[1]),
                    row[2],
                    row[3],
                    row[4].isoformat() if row[4] else "",
                    row[5].isoformat() if row[5] else "",
                    *row[6:],
                )
            )
        return discord.File(
            BytesIO(output.getvalue().encode("utf-8-sig")),
            filename="aestron-guild-activity.csv",
        )
