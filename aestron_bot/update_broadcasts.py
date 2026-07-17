"""Consent-based bot update subscriptions, delivery, and history."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

import discord
from discord.ext import commands

from runtime_info import runtime_info

LOGGER = logging.getLogger(__name__)
BroadcastStatus = Literal["operational", "degraded", "maintenance", "resolved"]
STATUS_LABELS: dict[str, tuple[str, int]] = {
    "operational": ("All systems operational", 0x57F287),
    "degraded": ("Degraded service", 0xFEE75C),
    "maintenance": ("Maintenance in progress", 0x5865F2),
    "resolved": ("Incident resolved", 0x57F287),
}


@dataclass(frozen=True, slots=True)
class BroadcastDraft:
    """Validated content awaiting an owner confirmation."""

    title: str
    summary: str
    details: str | None
    status: BroadcastStatus
    include_stats: bool
    created_by: int


class UpdateBroadcastService:
    """Persist subscriptions and deliver confirmed updates without fallbacks."""

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot used for guild and deployment data."""
        self.bot = bot

    async def start(self) -> None:
        """Create subscription, broadcast, and delivery history tables."""
        if not self.bot.database.connected:
            return
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_update_subscriptions (
                    guild_id BIGINT PRIMARY KEY,
                    channel_id BIGINT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    configured_by BIGINT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_broadcasts (
                    id BIGSERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details TEXT,
                    service_status TEXT NOT NULL,
                    include_stats BOOLEAN NOT NULL DEFAULT FALSE,
                    created_by BIGINT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CHECK (service_status IN
                        ('operational', 'degraded', 'maintenance', 'resolved'))
                )
                """
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_broadcast_deliveries (
                    broadcast_id BIGINT NOT NULL REFERENCES bot_broadcasts(id)
                        ON DELETE CASCADE,
                    guild_id BIGINT NOT NULL,
                    channel_id BIGINT,
                    delivery_status TEXT NOT NULL,
                    error_code TEXT,
                    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (broadcast_id, guild_id)
                )
                """
            )

    @staticmethod
    def usable_channel(
        guild: discord.Guild,
        channel: discord.TextChannel,
    ) -> tuple[bool, list[str]]:
        """Validate an explicit update destination without scanning channels."""
        if channel.guild.id != guild.id or guild.me is None:
            return False, ["view channel"]
        permissions = channel.permissions_for(guild.me)
        missing = [
            permission.replace("_", " ")
            for permission in ("view_channel", "send_messages", "embed_links")
            if not getattr(permissions, permission, False)
        ]
        return not missing, missing

    async def subscribe(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        configured_by: int,
    ) -> None:
        """Enable delivery to one explicit, permission-checked channel."""
        usable, missing = self.usable_channel(guild, channel)
        if not usable:
            raise commands.BotMissingPermissions(
                [permission.replace(" ", "_") for permission in missing]
            )
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO guild_update_subscriptions
                    (guild_id, channel_id, enabled, configured_by)
                VALUES ($1, $2, TRUE, $3)
                ON CONFLICT (guild_id) DO UPDATE SET
                    channel_id = EXCLUDED.channel_id,
                    enabled = TRUE,
                    configured_by = EXCLUDED.configured_by,
                    updated_at = NOW()
                """,
                guild.id,
                channel.id,
                configured_by,
            )

    async def unsubscribe(self, guild_id: int) -> None:
        """Disable a subscription while retaining its audit metadata."""
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE guild_update_subscriptions
                SET enabled = FALSE, updated_at = NOW()
                WHERE guild_id = $1
                """,
                guild_id,
            )

    async def subscription_embed(self, guild: discord.Guild) -> discord.Embed:
        """Show whether and where the server consented to receive updates."""
        async with self.bot.database.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM guild_update_subscriptions WHERE guild_id = $1",
                guild.id,
            )
        embed = discord.Embed(title="Aestron update subscription", color=0x5865F2)
        if row is None or not row["enabled"]:
            embed.description = (
                "Updates are not subscribed. A server manager can choose a channel "
                "with `/updates subscribe`. Aestron never searches for another "
                "channel or broadcasts here without this consent."
            )
            return embed
        channel = guild.get_channel(int(row["channel_id"]))
        embed.description = "This server has opted in to important Aestron updates."
        embed.add_field(
            name="Destination",
            value=getattr(channel, "mention", f"Missing channel `{row['channel_id']}`"),
        )
        embed.add_field(
            name="Last changed",
            value=discord.utils.format_dt(row["updated_at"], "R"),
        )
        return embed

    async def recipient_count(self) -> int:
        """Return the number of currently enabled subscriptions."""
        async with self.bot.database.pool.acquire() as connection:
            value = await connection.fetchval(
                "SELECT COUNT(*) FROM guild_update_subscriptions WHERE enabled = TRUE"
            )
        return int(value or 0)

    def embed(self, draft: BroadcastDraft) -> discord.Embed:
        """Render one bounded release and service-status announcement."""
        status_label, color = STATUS_LABELS[draft.status]
        settings = self.bot.runtime_settings
        deployment = runtime_info()
        embed = discord.Embed(
            title=draft.title,
            description=draft.summary,
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Service status", value=status_label)
        embed.add_field(name="Version", value=f"`{settings.version}`")
        revision = deployment["git_commit_short"]
        if deployment["git_commit_url"]:
            revision = f"[`{revision}`]({deployment['git_commit_url']})"
        embed.add_field(name="Revision", value=revision)
        if draft.details:
            embed.add_field(name="What changed", value=draft.details, inline=False)
        if draft.include_stats:
            launched_at = getattr(self.bot, "launch_time", discord.utils.utcnow())
            uptime = discord.utils.utcnow() - launched_at
            embed.add_field(
                name="Live bot status",
                value=(
                    f"Uptime: **{str(timedelta(seconds=int(uptime.total_seconds())))}**\n"
                    f"Gateway: **{self.bot.latency * 1000:.0f} ms**\n"
                    f"Servers: **{len(self.bot.guilds):,}**"
                ),
                inline=False,
            )
        if settings.site_base_url:
            embed.add_field(
                name="Release notes",
                value=f"[View the full update history]({settings.site_base_url}/updates)",
                inline=False,
            )
        embed.set_footer(text="You received this because your server opted in")
        return embed

    async def broadcast(self, draft: BroadcastDraft) -> discord.Embed:
        """Send one confirmed update and persist per-guild delivery results."""
        async with self.bot.database.pool.acquire() as connection:
            subscriptions = await connection.fetch(
                """
                SELECT guild_id, channel_id FROM guild_update_subscriptions
                WHERE enabled = TRUE ORDER BY guild_id
                """
            )
            broadcast_id = await connection.fetchval(
                """
                INSERT INTO bot_broadcasts
                    (title, summary, details, service_status,
                     include_stats, created_by)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                draft.title,
                draft.summary,
                draft.details,
                draft.status,
                draft.include_stats,
                draft.created_by,
            )

        delivered = unavailable = failed = 0
        delivery_rows = []
        for row in subscriptions:
            guild_id = int(row["guild_id"])
            channel_id = int(row["channel_id"])
            guild = self.bot.get_guild(guild_id)
            channel = guild.get_channel(channel_id) if guild is not None else None
            if guild is None or not isinstance(channel, discord.TextChannel):
                unavailable += 1
                delivery_rows.append(
                    (broadcast_id, guild_id, channel_id, "unavailable", "missing")
                )
                continue
            usable, missing = self.usable_channel(guild, channel)
            if not usable:
                unavailable += 1
                delivery_rows.append(
                    (
                        broadcast_id,
                        guild_id,
                        channel_id,
                        "unavailable",
                        "permissions:" + ",".join(missing),
                    )
                )
                continue
            try:
                await channel.send(
                    embed=self.embed(draft),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.Forbidden:
                failed += 1
                status, error_code = "failed", "forbidden"
            except discord.HTTPException as error:
                failed += 1
                status, error_code = "failed", f"http_{error.status}"
            else:
                delivered += 1
                status, error_code = "delivered", None
            delivery_rows.append(
                (broadcast_id, guild_id, channel_id, status, error_code)
            )
            await asyncio.sleep(0.25)

        if delivery_rows:
            async with self.bot.database.pool.acquire() as connection:
                await connection.executemany(
                    """
                    INSERT INTO bot_broadcast_deliveries
                        (broadcast_id, guild_id, channel_id,
                         delivery_status, error_code)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    delivery_rows,
                )
        LOGGER.info(
            "Bot update broadcast=%s delivered=%s unavailable=%s failed=%s",
            broadcast_id,
            delivered,
            unavailable,
            failed,
        )
        result = discord.Embed(title="Update broadcast complete", color=0x57F287)
        result.description = (
            f"Broadcast **#{broadcast_id}** finished. No fallback channels were used."
        )
        result.add_field(name="Delivered", value=str(delivered))
        result.add_field(name="Unavailable", value=str(unavailable))
        result.add_field(name="Failed", value=str(failed))
        return result

    async def history_embed(self) -> discord.Embed:
        """Return recent broadcasts and their persisted delivery totals."""
        async with self.bot.database.pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT b.id, b.title, b.service_status, b.created_at,
                    COUNT(*) FILTER (WHERE d.delivery_status = 'delivered') delivered,
                    COUNT(*) FILTER (WHERE d.delivery_status = 'unavailable') unavailable,
                    COUNT(*) FILTER (WHERE d.delivery_status = 'failed') failed
                FROM bot_broadcasts b
                LEFT JOIN bot_broadcast_deliveries d ON d.broadcast_id = b.id
                GROUP BY b.id
                ORDER BY b.created_at DESC
                LIMIT 10
                """
            )
        embed = discord.Embed(title="Recent Aestron broadcasts", color=0x5865F2)
        embed.description = (
            "\n".join(
                f"**#{row['id']} · {row['title'][:50]}** "
                f"({row['service_status']}) · "
                f"{row['delivered']} sent / {row['unavailable']} unavailable / "
                f"{row['failed']} failed · "
                f"{discord.utils.format_dt(row['created_at'], 'R')}"
                for row in rows
            )[:4000]
            or "No confirmed broadcasts have been sent."
        )
        return embed


class BroadcastConfirmationView(discord.ui.View):
    """Require an explicit owner confirmation before sending any update."""

    def __init__(
        self,
        service: UpdateBroadcastService,
        draft: BroadcastDraft,
        recipient_count: int,
    ) -> None:
        """Store the immutable draft and intended subscriber count."""
        super().__init__(timeout=120)
        self.service = service
        self.draft = draft
        self.recipient_count = recipient_count
        self.message: discord.WebhookMessage | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Prevent another user from confirming the owner's broadcast."""
        if interaction.user.id == self.draft.created_by:
            return True
        await interaction.response.send_message(
            "Only the owner who created this preview can use it.", ephemeral=True
        )
        return False

    def _disable(self) -> None:
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Send update", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Deliver the confirmed update sequentially to subscribed channels."""
        await interaction.response.defer()
        self._disable()
        await interaction.edit_original_response(view=self)
        result = await self.service.broadcast(self.draft)
        await interaction.edit_original_response(embed=result, view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Discard the draft without creating a broadcast record."""
        self._disable()
        embed = discord.Embed(
            title="Broadcast cancelled",
            description="No guild received this update.",
            color=discord.Color.dark_grey(),
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    async def on_timeout(self) -> None:
        """Expire the preview safely without sending anything."""
        self._disable()
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)
