"""Rate-window anti-raid protection backed by Discord audit logs."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

import discord
from discord import app_commands
from discord.ext import commands

from .audit_logging import AuditEvent

LOGGER = logging.getLogger(__name__)
DANGEROUS_ACTIONS = frozenset(
    {
        discord.AuditLogAction.channel_create,
        discord.AuditLogAction.channel_delete,
        discord.AuditLogAction.channel_update,
        discord.AuditLogAction.role_create,
        discord.AuditLogAction.role_delete,
        discord.AuditLogAction.role_update,
        discord.AuditLogAction.guild_update,
        discord.AuditLogAction.ban,
        discord.AuditLogAction.kick,
        discord.AuditLogAction.unban,
        discord.AuditLogAction.webhook_create,
        discord.AuditLogAction.webhook_delete,
        discord.AuditLogAction.webhook_update,
    }
)
DANGEROUS_PERMISSIONS = (
    "administrator",
    "manage_guild",
    "manage_channels",
    "manage_roles",
    "manage_webhooks",
    "ban_members",
    "kick_members",
)


class AntiRaid(commands.Cog):
    """Detect bursts of destructive audit actions and remove dangerous roles."""

    antiraid = app_commands.Group(
        name="antiraid", description="Configure server anti-raid protection."
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Create in-memory rate windows and incident cooldowns."""
        self.bot = bot
        self._windows: dict[tuple[int, int], deque[float]] = defaultdict(deque)
        self._incidents: dict[tuple[int, int], float] = {}

    async def cog_load(self) -> None:
        """Create anti-raid configuration and incident tables."""
        if not self.bot.database.connected:
            return
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS antiraid ("
                "channelid BIGINT NOT NULL, guildid BIGINT PRIMARY KEY)"
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS antiraid_settings (
                    guild_id BIGINT PRIMARY KEY,
                    log_channel_id BIGINT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    action TEXT NOT NULL DEFAULT 'remove_roles',
                    threshold SMALLINT NOT NULL DEFAULT 3,
                    window_seconds SMALLINT NOT NULL DEFAULT 20,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CHECK (action IN ('log_only', 'remove_roles')),
                    CHECK (threshold BETWEEN 2 AND 10),
                    CHECK (window_seconds BETWEEN 5 AND 120)
                )
                """
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS antiraid_incidents (
                    id BIGSERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    actor_id BIGINT NOT NULL,
                    event_type TEXT NOT NULL,
                    action_taken TEXT NOT NULL,
                    event_count SMALLINT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await connection.execute(
                """
                INSERT INTO antiraid_settings (guild_id, log_channel_id)
                SELECT guildid, channelid FROM antiraid
                ON CONFLICT (guild_id) DO NOTHING
                """
            )

    async def _settings(self, guild_id: int):
        async with self.bot.database.pool.acquire() as connection:
            return await connection.fetchrow(
                "SELECT * FROM antiraid_settings WHERE guild_id = $1", guild_id
            )

    @staticmethod
    def _dangerous_role(role: discord.Role) -> bool:
        return any(
            getattr(role.permissions, name, False) for name in DANGEROUS_PERMISSIONS
        )

    async def _remove_dangerous_roles(
        self, member: discord.Member, reason: str
    ) -> list[str]:
        guild = member.guild
        bot_member = guild.me
        if bot_member is None:
            return []
        removable = [
            role
            for role in member.roles
            if role != guild.default_role
            and not role.managed
            and role < bot_member.top_role
            and self._dangerous_role(role)
        ]
        if not removable:
            return []
        await member.remove_roles(*removable, reason=reason[:512], atomic=True)
        return [role.name for role in removable]

    async def process_audit_event(self, event: AuditEvent) -> None:
        """Record one attributed action and enforce configured burst limits."""
        if event.action not in DANGEROUS_ACTIONS or event.actor is None:
            return
        guild = event.guild
        actor_id = event.actor.id
        if actor_id in {guild.owner_id, getattr(self.bot.user, "id", None)}:
            return
        settings = await self._settings(guild.id)
        if not settings or not settings["enabled"]:
            return
        now = time.monotonic()
        window = self._windows[(guild.id, actor_id)]
        window_seconds = int(settings["window_seconds"])
        while window and window[0] <= now - window_seconds:
            window.popleft()
        window.append(now)
        threshold = int(settings["threshold"])
        if len(window) < threshold:
            return
        incident_key = (guild.id, actor_id)
        if self._incidents.get(incident_key, 0) > now - 300:
            return
        self._incidents[incident_key] = now

        member = guild.get_member(actor_id)
        action_taken = "logged"
        removed: list[str] = []
        if settings["action"] == "remove_roles" and member is not None:
            try:
                removed = await self._remove_dangerous_roles(
                    member,
                    "Aestron anti-raid: destructive audit action threshold exceeded",
                )
                action_taken = "removed_roles" if removed else "unable_to_remove_roles"
            except (discord.Forbidden, discord.HTTPException):
                action_taken = "role_removal_failed"
                LOGGER.exception(
                    "Anti-raid role removal failed guild=%s actor=%s",
                    guild.id,
                    actor_id,
                )

        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO antiraid_incidents "
                "(guild_id, actor_id, event_type, action_taken, event_count) "
                "VALUES ($1, $2, $3, $4, $5)",
                guild.id,
                actor_id,
                event.kind,
                action_taken,
                len(window),
            )
        channel = guild.get_channel(int(settings["log_channel_id"]))
        if isinstance(channel, discord.TextChannel):
            embed = discord.Embed(
                title="🚨 Anti-raid threshold exceeded",
                description=(
                    f"{event.actor.mention} performed **{len(window)}** destructive "
                    f"actions within **{window_seconds}s**."
                ),
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="Latest event", value=event.kind)
            embed.add_field(name="Action", value=action_taken.replace("_", " ").title())
            embed.add_field(
                name="Roles removed", value=", ".join(removed)[:1024] or "None"
            )
            embed.set_footer(text=f"Actor ID: {actor_id}")
            try:
                await channel.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.warning("Could not send anti-raid alert guild=%s", guild.id)
        window.clear()

    async def _enable(self, guild: discord.Guild, channel: discord.TextChannel) -> None:
        if channel.guild.id != guild.id:
            raise commands.BadArgument("Choose a text channel in this server.")
        if guild.me is None:
            raise commands.BotMissingPermissions(["view_channel"])
        permissions = channel.permissions_for(guild.me)
        missing = [
            name
            for name in (
                "view_channel",
                "send_messages",
                "embed_links",
                "view_audit_log",
            )
            if not getattr(permissions, name, False)
        ]
        if missing:
            raise commands.BotMissingPermissions(missing)
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO antiraid_settings "
                "(guild_id, log_channel_id, enabled) VALUES ($1, $2, TRUE) "
                "ON CONFLICT (guild_id) DO UPDATE SET "
                "log_channel_id = EXCLUDED.log_channel_id, enabled = TRUE, updated_at = NOW()",
                guild.id,
                channel.id,
            )
            await connection.execute(
                "INSERT INTO antiraid (guildid, channelid) VALUES ($1, $2) "
                "ON CONFLICT (guildid) DO UPDATE SET channelid = EXCLUDED.channelid",
                guild.id,
                channel.id,
            )

    async def _disable(self, guild_id: int) -> None:
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "UPDATE antiraid_settings SET enabled = FALSE, updated_at = NOW() "
                "WHERE guild_id = $1",
                guild_id,
            )
            await connection.execute(
                "DELETE FROM antiraid WHERE guildid = $1", guild_id
            )
        for key in [key for key in self._windows if key[0] == guild_id]:
            self._windows.pop(key, None)

    async def status_embed(self, guild: discord.Guild) -> discord.Embed:
        """Build anti-raid configuration and recent-incident status."""
        settings = await self._settings(guild.id)
        async with self.bot.database.pool.acquire() as connection:
            incidents = await connection.fetch(
                "SELECT actor_id, event_type, action_taken, created_at "
                "FROM antiraid_incidents WHERE guild_id = $1 "
                "ORDER BY created_at DESC LIMIT 5",
                guild.id,
            )
        embed = discord.Embed(title="Anti-raid status", color=0xED4245)
        if not settings:
            embed.description = "Anti-raid has not been configured."
            return embed
        channel = guild.get_channel(int(settings["log_channel_id"]))
        embed.add_field(
            name="Protection",
            value="Enabled" if settings["enabled"] else "Disabled",
        )
        embed.add_field(
            name="Alert channel", value=getattr(channel, "mention", "Missing")
        )
        embed.add_field(name="Response", value=settings["action"].replace("_", " "))
        embed.add_field(
            name="Threshold",
            value=f"{settings['threshold']} destructive actions / {settings['window_seconds']}s",
            inline=False,
        )
        embed.add_field(
            name="Recent incidents",
            value="\n".join(
                f"{discord.utils.format_dt(row['created_at'], 'R')} · <@{row['actor_id']}> · "
                f"{row['event_type']} · {row['action_taken']}"
                for row in incidents
            )[:1024]
            or "None",
            inline=False,
        )
        return embed

    async def _configure(
        self, guild_id: int, action: str, threshold: int, window_seconds: int
    ) -> None:
        settings = await self._settings(guild_id)
        if not settings:
            raise commands.BadArgument("Enable anti-raid before configuring it.")
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "UPDATE antiraid_settings SET action = $1, threshold = $2, "
                "window_seconds = $3, updated_at = NOW() WHERE guild_id = $4",
                action,
                threshold,
                window_seconds,
                guild_id,
            )

    @commands.group(
        name="antiraid",
        invoke_without_command=True,
        brief="Configure and inspect anti-raid protection.",
        description=(
            "Configure audit-backed raid detection, enforcement thresholds, alerts, "
            "and incident history. Run without a subcommand to show status."
        ),
        usage="[enable|disable|status|configure]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def antiraid_prefix(self, ctx: commands.Context) -> None:
        """Show anti-raid status when no prefix subcommand is supplied."""
        await ctx.send(embed=await self.status_embed(ctx.guild), ephemeral=True)

    @antiraid_prefix.command(
        name="enable",
        brief="Enable anti-raid and select its alert channel.",
        description=(
            "Enable destructive-action burst detection and send incident alerts "
            "to the selected or current text channel."
        ),
        usage="[channel]",
    )
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def prefix_enable(
        self, ctx: commands.Context, channel: discord.TextChannel | None = None
    ) -> None:
        """Enable anti-raid through a prefix command."""
        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel):
            raise commands.BadArgument("Choose a text channel.")
        await self._enable(ctx.guild, target)
        await ctx.send(
            f"Anti-raid enabled. Alerts will be sent to {target.mention}.",
            ephemeral=True,
        )

    @antiraid_prefix.command(
        name="disable",
        brief="Disable anti-raid protection.",
        description="Disable enforcement immediately while retaining incident history.",
        usage="",
    )
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def prefix_disable(self, ctx: commands.Context) -> None:
        """Disable anti-raid through a prefix command."""
        await self._disable(ctx.guild.id)
        await ctx.send("Anti-raid is disabled.", ephemeral=True)

    @antiraid_prefix.command(
        name="status",
        brief="Show anti-raid health and recent incidents.",
        description=(
            "Show whether anti-raid is enabled, its alert destination, thresholds, "
            "response, and recent incidents."
        ),
        usage="",
    )
    @commands.cooldown(2, 10, commands.BucketType.guild)
    async def prefix_status(self, ctx: commands.Context) -> None:
        """Show current anti-raid health through a prefix command."""
        await ctx.send(embed=await self.status_embed(ctx.guild), ephemeral=True)

    @antiraid_prefix.command(
        name="configure",
        brief="Set the anti-raid response and rate window.",
        description=(
            "Choose `log_only` or `remove_roles`, then set the number of destructive "
            "actions allowed within a time window."
        ),
        usage="<log_only|remove_roles> [threshold=3] [window_seconds=20]",
    )
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def prefix_configure(
        self,
        ctx: commands.Context,
        action: str,
        threshold: int = 3,
        window_seconds: int = 20,
    ) -> None:
        """Configure anti-raid thresholds through a prefix command."""
        action = action.casefold()
        if action not in {"log_only", "remove_roles"}:
            raise commands.BadArgument("Action must be `log_only` or `remove_roles`.")
        if not 2 <= threshold <= 10:
            raise commands.BadArgument("Threshold must be between 2 and 10.")
        if not 5 <= window_seconds <= 120:
            raise commands.BadArgument("Window seconds must be between 5 and 120.")
        await self._configure(ctx.guild.id, action, threshold, window_seconds)
        await ctx.send(
            f"Anti-raid set to **{action.replace('_', ' ')}** at "
            f"**{threshold}** actions per **{window_seconds}s**.",
            ephemeral=True,
        )

    @antiraid.command(name="enable", description="Enable anti-raid protection.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.guild_id)
    async def slash_enable(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        """Enable anti-raid through slash commands."""
        await self._enable(interaction.guild, channel)
        await interaction.response.send_message(
            f"Anti-raid enabled. Alerts will be sent to {channel.mention}.",
            ephemeral=True,
        )

    @antiraid.command(name="disable", description="Disable anti-raid protection.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.guild_id)
    async def slash_disable(self, interaction: discord.Interaction) -> None:
        """Disable anti-raid through slash commands."""
        await self._disable(interaction.guild_id)
        await interaction.response.send_message(
            "Anti-raid is disabled.", ephemeral=True
        )

    @antiraid.command(name="status", description="Show anti-raid health and incidents.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(2, 10, key=lambda interaction: interaction.guild_id)
    async def slash_status(self, interaction: discord.Interaction) -> None:
        """Show anti-raid status through slash commands."""
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            embed=await self.status_embed(interaction.guild), ephemeral=True
        )

    @antiraid.command(
        name="configure", description="Set anti-raid response and limits."
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.guild_id)
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Log only", value="log_only"),
            app_commands.Choice(name="Remove dangerous roles", value="remove_roles"),
        ]
    )
    async def slash_configure(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        threshold: app_commands.Range[int, 2, 10] = 3,
        window_seconds: app_commands.Range[int, 5, 120] = 20,
    ) -> None:
        """Configure anti-raid through slash commands."""
        await self._configure(
            interaction.guild_id, action.value, threshold, window_seconds
        )
        await interaction.response.send_message(
            f"Anti-raid set to **{action.name}** at **{threshold}** actions per "
            f"**{window_seconds}s**.",
            ephemeral=True,
        )
