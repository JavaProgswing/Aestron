"""Fast, persistent bot activity statistics and the ``stats`` command."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import Counter
from datetime import timedelta
from typing import Any

import asyncpg
import discord
import psutil
from discord.ext import commands

from runtime_info import runtime_info

LOGGER = logging.getLogger(__name__)


class BotStatistics:
    """Collect counters in memory and flush them to PostgreSQL in batches."""

    def __init__(self, *, flush_interval: float = 5.0) -> None:
        """Initialize in-memory and pending counters."""
        self.flush_interval = flush_interval
        self._pool: asyncpg.Pool | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._pending = Counter[str]()
        self.command_usage = Counter[str]()
        self.commands_used = 0
        self.commands_succeeded = 0
        self.commands_failed = 0
        self.guilds_joined = 0
        self.guilds_left = 0
        self.launches = 0
        self.session_commands = 0
        self.persistent = False

    async def start(self, pool: asyncpg.Pool) -> None:
        """Create the schema, load counters, and begin batched persistence."""
        self._pool = pool
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_runtime_stats (
                        singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
                        commands_used BIGINT NOT NULL DEFAULT 0,
                        commands_succeeded BIGINT NOT NULL DEFAULT 0,
                        commands_failed BIGINT NOT NULL DEFAULT 0,
                        guilds_joined BIGINT NOT NULL DEFAULT 0,
                        guilds_left BIGINT NOT NULL DEFAULT 0,
                        launches BIGINT NOT NULL DEFAULT 0,
                        last_started_at TIMESTAMPTZ,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                await connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_command_usage (
                        command_name TEXT PRIMARY KEY,
                        uses BIGINT NOT NULL DEFAULT 0,
                        last_used_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                await connection.execute(
                    """
                    INSERT INTO bot_runtime_stats (singleton, launches, last_started_at)
                    VALUES (TRUE, 1, NOW())
                    ON CONFLICT (singleton) DO UPDATE
                    SET launches = bot_runtime_stats.launches + 1,
                        last_started_at = NOW(),
                        updated_at = NOW()
                    """
                )
                totals = await connection.fetchrow(
                    "SELECT * FROM bot_runtime_stats WHERE singleton = TRUE"
                )
                command_rows = await connection.fetch(
                    "SELECT command_name, uses FROM bot_command_usage"
                )
        except Exception:
            LOGGER.exception(
                "Statistics persistence could not be initialized; using memory only"
            )
            return

        if totals is not None:
            self.commands_used = totals["commands_used"]
            self.commands_succeeded = totals["commands_succeeded"]
            self.commands_failed = totals["commands_failed"]
            self.guilds_joined = totals["guilds_joined"]
            self.guilds_left = totals["guilds_left"]
            self.launches = totals["launches"]
        self.command_usage.update(
            {row["command_name"]: row["uses"] for row in command_rows}
        )
        self.persistent = True
        self._flush_task = asyncio.create_task(
            self._flush_loop(), name="aestron-statistics-flush"
        )
        LOGGER.info("Persistent bot statistics initialized")

    def record_command(self, command_name: str) -> None:
        """Record a command invocation without performing database I/O."""
        name = command_name.casefold()
        self.commands_used += 1
        self.session_commands += 1
        self.command_usage[name] += 1
        self._pending["commands_used"] += 1
        self._pending[f"command:{name}"] += 1

    def record_outcome(self, *, succeeded: bool) -> None:
        """Record whether an invoked command completed successfully."""
        key = "commands_succeeded" if succeeded else "commands_failed"
        setattr(self, key, getattr(self, key) + 1)
        self._pending[key] += 1

    def record_guild_join(self) -> None:
        """Record a guild join without database I/O."""
        self.guilds_joined += 1
        self._pending["guilds_joined"] += 1

    def record_guild_remove(self) -> None:
        """Record a guild removal without database I/O."""
        self.guilds_left += 1
        self._pending["guilds_left"] += 1

    def snapshot(self) -> dict[str, Any]:
        """Return a consistent in-memory snapshot for commands and monitoring."""
        return {
            "commands_used": self.commands_used,
            "commands_succeeded": self.commands_succeeded,
            "commands_failed": self.commands_failed,
            "guilds_joined": self.guilds_joined,
            "guilds_left": self.guilds_left,
            "launches": self.launches,
            "session_commands": self.session_commands,
            "top_commands": self.command_usage.most_common(5),
            "persistent": self.persistent,
        }

    async def flush(self) -> None:
        """Write pending deltas in one transaction."""
        if not self.persistent or self._pool is None or not self._pending:
            return

        pending = self._pending
        self._pending = Counter()
        command_deltas = [
            (key.removeprefix("command:"), value)
            for key, value in pending.items()
            if key.startswith("command:")
        ]
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await connection.execute(
                        """
                        UPDATE bot_runtime_stats
                        SET commands_used = commands_used + $1,
                            commands_succeeded = commands_succeeded + $2,
                            commands_failed = commands_failed + $3,
                            guilds_joined = guilds_joined + $4,
                            guilds_left = guilds_left + $5,
                            updated_at = NOW()
                        WHERE singleton = TRUE
                        """,
                        pending["commands_used"],
                        pending["commands_succeeded"],
                        pending["commands_failed"],
                        pending["guilds_joined"],
                        pending["guilds_left"],
                    )
                    if command_deltas:
                        await connection.executemany(
                            """
                            INSERT INTO bot_command_usage
                                (command_name, uses, last_used_at)
                            VALUES ($1, $2, NOW())
                            ON CONFLICT (command_name) DO UPDATE
                            SET uses = bot_command_usage.uses + EXCLUDED.uses,
                                last_used_at = NOW()
                            """,
                            command_deltas,
                        )
        except asyncio.CancelledError:
            self._pending.update(pending)
            raise
        except Exception:
            self._pending.update(pending)
            LOGGER.exception("Could not flush bot statistics; counters will be retried")

    async def close(self) -> None:
        """Stop the worker and persist the final counter batch."""
        if self._flush_task is not None:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None
        await self.flush()

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval)
            await self.flush()


class Statistics(commands.Cog):
    """Track bot activity and expose a concise runtime statistics command."""

    def __init__(self, bot: commands.Bot, statistics: BotStatistics) -> None:
        """Bind the shared collector to command and guild events."""
        self.bot = bot
        self.statistics = statistics

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context) -> None:
        """Count every recognized command invocation."""
        if ctx.command is not None:
            self.statistics.record_command(ctx.command.qualified_name)

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context) -> None:
        """Count successful command completions."""
        self.statistics.record_outcome(succeeded=True)

    @commands.Cog.listener()
    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        """Count command invocations that dispatch an error."""
        if ctx.command is not None:
            self.statistics.record_outcome(succeeded=False)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Count guild joins."""
        self.statistics.record_guild_join()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Count guild removals."""
        self.statistics.record_guild_remove()

    @commands.hybrid_command(
        name="stats",
        aliases=["botstats", "statistics"],
        brief="Show command usage, guild, uptime, and runtime activity.",
        description=(
            "Show persistent command counts, guild activity, uptime, latency, "
            "resource usage, and music health."
        ),
        usage="",
    )
    async def stats(self, ctx: commands.Context) -> None:
        """Display persistent and current-session activity statistics."""
        data = self.statistics.snapshot()
        uptime = discord.utils.utcnow() - self.bot.launch_time
        process = psutil.Process()
        memory_mib = process.memory_info().rss / 1024 / 1024
        cpu_percent = psutil.cpu_percent(interval=None)
        member_count = sum(guild.member_count or 0 for guild in self.bot.guilds)

        activity = self.bot.activity
        activity_text = "None"
        if activity is not None:
            activity_type = getattr(activity.type, "name", "custom").replace("_", " ")
            activity_text = f"{activity_type.title()}: {activity.name}"

        lavalink = getattr(self.bot, "lavalink", None)
        node_status = "Unavailable"
        active_players = 0
        if lavalink is not None and lavalink.connected:
            node_status = f"Connected ({lavalink.version or 'version unknown'})"
            active_players = len(lavalink.node.players)

        top_commands = (
            "\n".join(f"`{name}` — {uses:,}" for name, uses in data["top_commands"])
            or "No commands recorded yet."
        )
        uptime_text = str(timedelta(seconds=int(uptime.total_seconds())))
        deployment = runtime_info()

        embed = discord.Embed(
            title=f"{self.bot.user.name if self.bot.user else 'Aestron'} statistics",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Commands",
            value=(
                f"Used: **{data['commands_used']:,}**\n"
                f"Succeeded: **{data['commands_succeeded']:,}**\n"
                f"Failed: **{data['commands_failed']:,}**\n"
                f"This session: **{data['session_commands']:,}**"
            ),
        )
        embed.add_field(
            name="Guilds",
            value=(
                f"Current: **{len(self.bot.guilds):,}**\n"
                f"Members: **{member_count:,}**\n"
                f"Joined: **{data['guilds_joined']:,}**\n"
                f"Left: **{data['guilds_left']:,}**"
            ),
        )
        embed.add_field(
            name="Activity",
            value=(
                f"{activity_text}\n"
                f"Uptime: **{uptime_text}**\n"
                f"Latency: **{self.bot.latency * 1000:.0f} ms**\n"
                f"Launches tracked: **{data['launches']:,}**"
            ),
        )
        embed.add_field(name="Top commands", value=top_commands, inline=False)
        embed.add_field(
            name="Voice",
            value=f"Lavalink: **{node_status}**\nActive players: **{active_players}**",
        )
        embed.add_field(
            name="Process",
            value=(
                f"CPU: **{cpu_percent:.1f}%**\n"
                f"RAM: **{memory_mib:.1f} MiB**\n"
                f"Version: **{deployment['version']}**\n"
                f"Commit: `{deployment['git_commit_short']}`"
            ),
        )
        embed.set_footer(
            text=(
                "Persistent PostgreSQL counters"
                if data["persistent"]
                else "In-memory counters (database schema unavailable)"
            )
        )
        await ctx.send(embed=embed)
