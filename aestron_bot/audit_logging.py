"""Reliable guild audit logging and configuration overview."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Normalized guild audit event shared with anti-raid."""

    guild: discord.Guild
    kind: str
    action: discord.AuditLogAction | None
    target_id: int | None
    target: str
    actor: discord.abc.User | None
    reason: str | None
    occurred_at: datetime
    changes: str = ""


def _channel_permissions(
    channel: discord.TextChannel, member: discord.Member
) -> list[str]:
    permissions = channel.permissions_for(member)
    required = ("view_channel", "send_messages", "embed_links", "view_audit_log")
    return [name for name in required if not getattr(permissions, name, False)]


class AuditLogging(commands.Cog):
    """Configurable event logging with recent-event persistence."""

    logs = app_commands.Group(
        name="logs", description="Configure and inspect guild logs."
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize a short-lived configuration cache."""
        self.bot = bot
        self._channel_cache: dict[int, tuple[float, int | None]] = {}
        self._events_since_cleanup = 0

    async def cog_load(self) -> None:
        """Create the bounded event history table."""
        if not self.bot.database.connected:
            return
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS logchannels ("
                "guildid BIGINT PRIMARY KEY, channelid BIGINT NOT NULL)"
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_log_events (
                    id BIGSERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id BIGINT,
                    target_id BIGINT,
                    summary TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await connection.execute(
                "CREATE INDEX IF NOT EXISTS guild_log_events_guild_created_idx "
                "ON guild_log_events (guild_id, created_at DESC)"
            )

    async def _channel_id(self, guild_id: int) -> int | None:
        cached = self._channel_cache.get(guild_id)
        now = time.monotonic()
        if cached and cached[0] > now:
            return cached[1]
        async with self.bot.database.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT channelid FROM logchannels WHERE guildid = $1", guild_id
            )
        channel_id = int(row["channelid"]) if row else None
        self._channel_cache[guild_id] = (now + 60, channel_id)
        return channel_id

    def _invalidate(self, guild_id: int) -> None:
        self._channel_cache.pop(guild_id, None)

    async def _find_entry(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int | None,
    ) -> discord.AuditLogEntry | None:
        if guild.me is None or not guild.me.guild_permissions.view_audit_log:
            return None
        for attempt in range(3):
            if attempt:
                await asyncio.sleep(0.6)
            try:
                async for entry in guild.audit_logs(limit=6, action=action):
                    age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                    entry_target_id = getattr(entry.target, "id", None)
                    if age <= 15 and (
                        target_id is None or entry_target_id == target_id
                    ):
                        return entry
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.warning(
                    "Could not read audit log guild=%s", guild.id, exc_info=True
                )
                return None
        return None

    async def dispatch(
        self,
        guild: discord.Guild,
        *,
        kind: str,
        title: str,
        target: str,
        target_id: int | None = None,
        action: discord.AuditLogAction | None = None,
        changes: str = "",
        color: discord.Color = discord.Color.blurple(),
        actor_override: discord.abc.User | None = None,
        reason_override: str | None = None,
    ) -> None:
        """Resolve attribution, persist a summary, and publish one event."""
        entry = (
            await self._find_entry(guild, action, target_id)
            if action and actor_override is None
            else None
        )
        actor = actor_override or (entry.user if entry else None)
        reason = reason_override or (entry.reason if entry else None)
        event = AuditEvent(
            guild=guild,
            kind=kind,
            action=action,
            target_id=target_id,
            target=target,
            actor=actor,
            reason=reason,
            occurred_at=discord.utils.utcnow(),
            changes=changes,
        )
        summary = f"{title}: {target}"[:500]
        try:
            async with self.bot.database.pool.acquire() as connection:
                await connection.execute(
                    "INSERT INTO guild_log_events "
                    "(guild_id, event_type, actor_id, target_id, summary) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    guild.id,
                    kind,
                    getattr(actor, "id", None),
                    target_id,
                    summary,
                )
                self._events_since_cleanup += 1
                if self._events_since_cleanup >= 100:
                    await connection.execute(
                        "DELETE FROM guild_log_events "
                        "WHERE created_at < NOW() - INTERVAL '90 days'"
                    )
                    self._events_since_cleanup = 0
        except Exception:
            LOGGER.exception("Could not persist guild log event guild=%s", guild.id)

        anti_raid = self.bot.get_cog("AntiRaid")
        if anti_raid is not None and action is not None:
            await anti_raid.process_audit_event(event)

        channel_id = await self._channel_id(guild.id)
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return
        embed = discord.Embed(title=title, color=color, timestamp=event.occurred_at)
        embed.add_field(name="Target", value=target[:1024], inline=False)
        embed.add_field(
            name="Actor",
            value=(f"{actor.mention} (`{actor.id}`)" if actor else "Unavailable"),
        )
        embed.add_field(name="Reason", value=(reason or "No reason provided")[:1024])
        if changes:
            embed.add_field(name="Changes", value=changes[:1024], inline=False)
        embed.set_footer(text=f"Event: {kind}")
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.warning(
                "Could not publish guild log event guild=%s channel=%s",
                guild.id,
                channel.id,
                exc_info=True,
            )

    async def _set_channel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> None:
        if channel.guild.id != guild.id:
            raise commands.BadArgument("Choose a text channel in this server.")
        if guild.me is None:
            raise commands.BotMissingPermissions(["view_channel"])
        missing = _channel_permissions(channel, guild.me)
        if missing:
            raise commands.BotMissingPermissions(missing)
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO logchannels (guildid, channelid) VALUES ($1, $2) "
                "ON CONFLICT (guildid) DO UPDATE SET channelid = EXCLUDED.channelid",
                guild.id,
                channel.id,
            )
        self._invalidate(guild.id)

    async def _disable(self, guild_id: int) -> None:
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "DELETE FROM logchannels WHERE guildid = $1", guild_id
            )
        self._invalidate(guild_id)

    async def overview_embed(self, guild: discord.Guild) -> discord.Embed:
        """Build a health and recent-activity overview for one guild."""
        channel_id = await self._channel_id(guild.id)
        channel = guild.get_channel(channel_id) if channel_id else None
        missing: list[str] = []
        if isinstance(channel, discord.TextChannel) and guild.me is not None:
            missing = _channel_permissions(channel, guild.me)
        guild_channel_ids = [channel.id for channel in guild.channels]
        async with self.bot.database.pool.acquire() as connection:
            counts = await connection.fetch(
                "SELECT event_type, COUNT(*) AS total FROM guild_log_events "
                "WHERE guild_id = $1 AND created_at > NOW() - INTERVAL '24 hours' "
                "GROUP BY event_type ORDER BY total DESC LIMIT 8",
                guild.id,
            )
            recent = await connection.fetch(
                "SELECT summary, created_at FROM guild_log_events "
                "WHERE guild_id = $1 ORDER BY created_at DESC LIMIT 5",
                guild.id,
            )
            anti = await connection.fetchrow(
                "SELECT enabled, action, threshold, window_seconds, log_channel_id "
                "FROM antiraid_settings WHERE guild_id = $1",
                guild.id,
            )
            automod_rows = {
                "spam": await connection.fetch(
                    "SELECT channelid FROM spamchannels "
                    "WHERE channelid = ANY($1::BIGINT[])",
                    guild_channel_ids,
                ),
                "links": await connection.fetch(
                    "SELECT channelid FROM linkchannels "
                    "WHERE channelid = ANY($1::BIGINT[])",
                    guild_channel_ids,
                ),
                "profanity": await connection.fetch(
                    "SELECT channelid FROM profanechannels "
                    "WHERE channelid = ANY($1::BIGINT[])",
                    guild_channel_ids,
                ),
            }
            active_tickets = await connection.fetchval(
                "SELECT COUNT(*) FROM support_tickets WHERE guild_id = $1 "
                "AND status IN ('open', 'locked')",
                guild.id,
            )
            verification = await connection.fetchrow(
                "SELECT enabled, channel_id, role_id FROM verification_settings "
                "WHERE guild_id = $1",
                guild.id,
            )
            active_giveaways = await connection.fetchval(
                "SELECT COUNT(*) FROM aestron_giveaways "
                "WHERE guild_id = $1 AND status = 'active'",
                guild.id,
            )
        embed = discord.Embed(title="Server safety & logs overview", color=0x5865F2)
        embed.add_field(
            name="Event logging",
            value=(
                f"Enabled in {channel.mention}"
                if isinstance(channel, discord.TextChannel)
                else "Disabled or configured channel was deleted"
            ),
            inline=False,
        )
        embed.add_field(
            name="Permission health",
            value="Ready"
            if not missing and channel
            else ", ".join(missing) or "Not configured",
            inline=False,
        )
        if anti:
            anti_channel = guild.get_channel(int(anti["log_channel_id"]))
            embed.add_field(
                name="Anti-raid",
                value=(
                    f"{'Enabled' if anti['enabled'] else 'Disabled'} · "
                    f"action `{anti['action']}` · {anti['threshold']} events / "
                    f"{anti['window_seconds']}s · "
                    f"channel {getattr(anti_channel, 'mention', 'missing')}"
                ),
                inline=False,
            )
        else:
            embed.add_field(name="Anti-raid", value="Not configured", inline=False)
        automod_summary = " · ".join(
            f"{feature}: {sum(guild.get_channel(int(row['channelid'])) is not None for row in rows)}"
            for feature, rows in automod_rows.items()
        )
        embed.add_field(
            name="AutoMod channel coverage",
            value=automod_summary or "No filters configured",
            inline=False,
        )
        verification_channel = (
            guild.get_channel(int(verification["channel_id"])) if verification else None
        )
        verification_role = (
            guild.get_role(int(verification["role_id"])) if verification else None
        )
        embed.add_field(
            name="Persistent services",
            value=(
                f"Open tickets: **{active_tickets or 0}** · Active giveaways: "
                f"**{active_giveaways or 0}**\nVerification: "
                + (
                    f"{'enabled' if verification['enabled'] else 'disabled'} · "
                    f"{getattr(verification_channel, 'mention', 'missing channel')} · "
                    f"{getattr(verification_role, 'mention', 'missing role')}"
                    if verification
                    else "not configured"
                )
            ),
            inline=False,
        )
        embed.add_field(
            name="Last 24 hours",
            value="\n".join(
                f"**{row['event_type']}** · {row['total']}" for row in counts
            )
            or "No recorded events",
        )
        embed.add_field(
            name="Recent events",
            value="\n".join(
                f"{discord.utils.format_dt(row['created_at'], 'R')} · {row['summary']}"
                for row in recent
            )[:1024]
            or "No recorded events",
            inline=False,
        )
        return embed

    @commands.hybrid_command(
        with_app_command=False,
        aliases=["setuplog", "setlogs", "enablelogs"],
        brief="Set the server event-log channel.",
        description="Validate permissions and configure the server event-log channel.",
        usage="[channel]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def setloggingchannel(
        self, ctx: commands.Context, channel: discord.TextChannel | None = None
    ) -> None:
        """Configure event logging through a prefix command."""
        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel):
            raise commands.BadArgument("Choose a text channel.")
        await self._set_channel(ctx.guild, target)
        await ctx.send(f"Event logs will be sent to {target.mention}.", ephemeral=True)

    @commands.hybrid_command(
        with_app_command=False,
        aliases=["disablelogs", "removelogs"],
        brief="Disable server event logging.",
        description="Remove the configured event-log destination for this server.",
        usage="",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def removeloggingchannel(self, ctx: commands.Context) -> None:
        """Disable event logging through a prefix command."""
        await self._disable(ctx.guild.id)
        await ctx.send("Event logging is disabled.", ephemeral=True)

    @commands.hybrid_command(
        with_app_command=False,
        aliases=["logstatus", "safetyoverview"],
        brief="Show logging and anti-raid health.",
        description="Show destinations, permissions, anti-raid settings, and recent events.",
        usage="",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def logoverview(self, ctx: commands.Context) -> None:
        """Show the safety overview through a prefix command."""
        await ctx.send(embed=await self.overview_embed(ctx.guild), ephemeral=True)

    @logs.command(name="setup", description="Set the server event-log channel.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.guild_id)
    async def slash_setup_logs(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        """Configure event logging through slash commands."""
        await self._set_channel(interaction.guild, channel)
        await interaction.response.send_message(
            f"Event logs will be sent to {channel.mention}.", ephemeral=True
        )

    @logs.command(name="disable", description="Disable server event logging.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.guild_id)
    async def slash_disable_logs(self, interaction: discord.Interaction) -> None:
        """Disable event logging through slash commands."""
        await self._disable(interaction.guild_id)
        await interaction.response.send_message(
            "Event logging is disabled.", ephemeral=True
        )

    @logs.command(name="overview", description="Show logging and anti-raid health.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(2, 10, key=lambda interaction: interaction.guild_id)
    async def slash_logs_overview(self, interaction: discord.Interaction) -> None:
        """Show the safety overview through slash commands."""
        await interaction.response.defer(ephemeral=True)
        embed = await self.overview_embed(interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        """Log channel creation."""
        await self.dispatch(
            channel.guild,
            kind="channel_create",
            title="Channel created",
            target=f"{channel.name} (`{channel.id}`)",
            target_id=channel.id,
            action=discord.AuditLogAction.channel_create,
            color=discord.Color.green(),
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """Log channel deletion."""
        await self.dispatch(
            channel.guild,
            kind="channel_delete",
            title="Channel deleted",
            target=f"{channel.name} (`{channel.id}`)",
            target_id=channel.id,
            action=discord.AuditLogAction.channel_delete,
            color=discord.Color.red(),
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel
    ) -> None:
        """Log relevant channel changes."""
        changes = []
        if before.name != after.name:
            changes.append(f"Name: `{before.name}` → `{after.name}`")
        if before.category_id != after.category_id:
            changes.append("Category changed")
        if before.overwrites != after.overwrites:
            changes.append("Permission overwrites changed")
        if not changes:
            return
        await self.dispatch(
            after.guild,
            kind="channel_update",
            title="Channel updated",
            target=f"{after.name} (`{after.id}`)",
            target_id=after.id,
            action=discord.AuditLogAction.channel_update,
            changes="\n".join(changes),
        )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        """Log role creation."""
        await self.dispatch(
            role.guild,
            kind="role_create",
            title="Role created",
            target=f"{role.name} (`{role.id}`)",
            target_id=role.id,
            action=discord.AuditLogAction.role_create,
            color=discord.Color.green(),
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        """Log role deletion."""
        await self.dispatch(
            role.guild,
            kind="role_delete",
            title="Role deleted",
            target=f"{role.name} (`{role.id}`)",
            target_id=role.id,
            action=discord.AuditLogAction.role_delete,
            color=discord.Color.red(),
        )

    @commands.Cog.listener()
    async def on_guild_role_update(
        self, before: discord.Role, after: discord.Role
    ) -> None:
        """Log relevant role changes."""
        changes = []
        if before.name != after.name:
            changes.append(f"Name: `{before.name}` → `{after.name}`")
        if before.permissions != after.permissions:
            changes.append("Permissions changed")
        if before.position != after.position:
            changes.append("Position changed")
        if not changes:
            return
        await self.dispatch(
            after.guild,
            kind="role_update",
            title="Role updated",
            target=f"{after.name} (`{after.id}`)",
            target_id=after.id,
            action=discord.AuditLogAction.role_update,
            changes="\n".join(changes),
        )

    @commands.Cog.listener()
    async def on_guild_update(
        self, before: discord.Guild, after: discord.Guild
    ) -> None:
        """Log relevant server-setting changes."""
        changes = []
        if before.name != after.name:
            changes.append(f"Name: `{before.name}` → `{after.name}`")
        if before.verification_level != after.verification_level:
            changes.append(
                f"Verification: `{before.verification_level}` → `{after.verification_level}`"
            )
        if not changes:
            return
        await self.dispatch(
            after,
            kind="guild_update",
            title="Server settings updated",
            target=f"{after.name} (`{after.id}`)",
            target_id=after.id,
            action=discord.AuditLogAction.guild_update,
            changes="\n".join(changes),
        )

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        """Log member bans."""
        await self.dispatch(
            guild,
            kind="member_ban",
            title="Member banned",
            target=f"{user} (`{user.id}`)",
            target_id=user.id,
            action=discord.AuditLogAction.ban,
            color=discord.Color.red(),
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        """Log member unbans."""
        await self.dispatch(
            guild,
            kind="member_unban",
            title="Member unbanned",
            target=f"{user} (`{user.id}`)",
            target_id=user.id,
            action=discord.AuditLogAction.unban,
            color=discord.Color.green(),
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Distinguish voluntary leaves from confirmed moderator kicks."""
        entry = await self._find_entry(
            member.guild, discord.AuditLogAction.kick, member.id
        )
        if entry is None:
            await self.dispatch(
                member.guild,
                kind="member_leave",
                title="Member left",
                target=f"{member} (`{member.id}`)",
                target_id=member.id,
                actor_override=member,
                color=discord.Color.dark_grey(),
            )
            return
        await self.dispatch(
            member.guild,
            kind="member_kick",
            title="Member kicked",
            target=f"{member} (`{member.id}`)",
            target_id=member.id,
            action=discord.AuditLogAction.kick,
            actor_override=entry.user,
            reason_override=entry.reason,
            color=discord.Color.orange(),
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Log new members with account-age context."""
        await self.dispatch(
            member.guild,
            kind="member_join",
            title="Member joined",
            target=f"{member} (`{member.id}`)",
            target_id=member.id,
            actor_override=member,
            changes=f"Account created {discord.utils.format_dt(member.created_at, 'R')}",
            color=discord.Color.green(),
        )

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        """Log invite creation with audit attribution when available."""
        if invite.guild is None:
            return
        await self.dispatch(
            invite.guild,
            kind="invite_create",
            title="Invite created",
            target=f"{invite.code} · {invite.channel}",
            target_id=None,
            action=discord.AuditLogAction.invite_create,
            changes=(
                f"Max uses: {invite.max_uses or 'unlimited'} · "
                f"Expires: {invite.max_age or 'never'} seconds"
            ),
            color=discord.Color.green(),
        )

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        """Log invite deletion with audit attribution when available."""
        if invite.guild is None:
            return
        await self.dispatch(
            invite.guild,
            kind="invite_delete",
            title="Invite deleted",
            target=f"{invite.code} · {invite.channel}",
            target_id=None,
            action=discord.AuditLogAction.invite_delete,
            color=discord.Color.red(),
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Log voice joins, moves, and leaves without audit-log polling."""
        if before.channel == after.channel:
            return
        if before.channel is None:
            title = "Voice joined"
            kind = "voice_join"
            changes = f"Joined {after.channel.mention}"
        elif after.channel is None:
            title = "Voice left"
            kind = "voice_leave"
            changes = f"Left {before.channel.mention}"
        else:
            title = "Voice moved"
            kind = "voice_move"
            changes = f"{before.channel.mention} → {after.channel.mention}"
        await self.dispatch(
            member.guild,
            kind=kind,
            title=title,
            target=f"{member} (`{member.id}`)",
            target_id=member.id,
            actor_override=member,
            changes=changes,
        )

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel) -> None:
        """Log and protect recent webhook mutations for a channel."""
        if (
            channel.guild.me is None
            or not channel.guild.me.guild_permissions.view_audit_log
        ):
            return
        try:
            async for entry in channel.guild.audit_logs(limit=1):
                if entry.action not in {
                    discord.AuditLogAction.webhook_create,
                    discord.AuditLogAction.webhook_update,
                    discord.AuditLogAction.webhook_delete,
                }:
                    return
                age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                if age > 15:
                    return
                target_id = getattr(entry.target, "id", None)
                await self.dispatch(
                    channel.guild,
                    kind=entry.action.name,
                    title=entry.action.name.replace("_", " ").title(),
                    target=f"{entry.target} (`{target_id or 'unknown'}`)",
                    target_id=target_id,
                    action=entry.action,
                    actor_override=entry.user,
                    reason_override=entry.reason,
                    color=discord.Color.orange(),
                )
                return
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.warning(
                "Could not inspect webhook audit event guild=%s",
                channel.guild.id,
                exc_info=True,
            )
