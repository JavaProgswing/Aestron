"""Discord commands for guild activity and consent-based bot updates."""

from __future__ import annotations

from datetime import timedelta
from typing import cast

import discord
from discord import app_commands
from discord.ext import commands

from .guild_activity import GuildActivityTracker
from .update_broadcasts import (
    BroadcastConfirmationView,
    BroadcastDraft,
    BroadcastStatus,
    UpdateBroadcastService,
)

OPERATIONS_COMMAND_NAMES = ("updates", "botadmin")


def scope_operations_commands(
    tree: app_commands.CommandTree,
    guild_id: int | None,
) -> discord.Object | None:
    """Move fleet-operation slash groups from global scope to one guild."""
    if guild_id is None:
        return None
    guild = discord.Object(id=guild_id)
    for command_name in OPERATIONS_COMMAND_NAMES:
        command = tree.remove_command(command_name)
        if command is None:
            raise RuntimeError(
                f"Application command group {command_name!r} is not registered."
            )
        tree.add_command(command, guild=guild, override=True)
    return guild


async def _owner_only(interaction: discord.Interaction) -> bool:
    """Allow application commands only for a configured Discord bot owner."""
    bot = interaction.client
    if isinstance(bot, commands.Bot) and await bot.is_owner(interaction.user):
        return True
    raise app_commands.CheckFailure("Only a configured bot owner can use this.")


class GuildOperations(commands.Cog):
    """Track guild activity and manage opt-in bot update announcements."""

    updates = app_commands.Group(
        name="updates",
        description="Choose where this server receives Aestron updates.",
    )
    botadmin = app_commands.Group(
        name="botadmin",
        description="Owner-only Aestron fleet operations.",
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Create modular activity and broadcast services."""
        self.bot = bot
        self.activity = GuildActivityTracker(bot)
        self.broadcasts = UpdateBroadcastService(bot)
        self._closed = False

    async def cog_load(self) -> None:
        """Initialize the two persistence services."""
        await self.broadcasts.start()
        await self.activity.start()

    async def close(self) -> None:
        """Flush activity and stop its background worker once."""
        if self._closed:
            return
        self._closed = True
        await self.activity.close()

    async def cog_unload(self) -> None:
        """Release background resources when the cog unloads."""
        await self.close()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Count guild messages without retaining message-level data."""
        if (
            message.guild is not None
            and message.webhook_id is None
            and not message.author.bot
        ):
            self.activity.record(message.guild.id, command=False)

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context) -> None:
        """Count recognized prefix-command attempts per guild."""
        if ctx.guild is not None and ctx.command is not None:
            self.activity.record(ctx.guild.id, command=True)

    @commands.Cog.listener()
    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: app_commands.Command | app_commands.ContextMenu,
    ) -> None:
        """Count completed application commands per guild."""
        del command
        if interaction.guild_id is not None:
            self.activity.record(interaction.guild_id, command=True)

    @commands.group(
        name="updates",
        invoke_without_command=True,
        brief="Configure official Aestron update announcements.",
        description=(
            "Opt this server into release and service-status announcements, select "
            "the exact destination, or inspect the current subscription."
        ),
        usage="[subscribe|unsubscribe|status]",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def updates_prefix(self, ctx: commands.Context) -> None:
        """Show the current update subscription."""
        embed = await self.broadcasts.subscription_embed(ctx.guild)
        await ctx.send(embed=embed, ephemeral=True)

    @updates_prefix.command(
        name="subscribe",
        brief="Subscribe an explicit channel to official bot updates.",
        description=(
            "Receive release and service-status announcements in the selected or "
            "current text or announcement channel."
        ),
        usage="[channel]",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.cooldown(1, 20, commands.BucketType.guild)
    async def updates_subscribe_prefix(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Subscribe through a prefix command."""
        destination = channel or ctx.channel
        if not isinstance(destination, discord.TextChannel):
            raise commands.BadArgument("Choose a text or announcement channel.")
        await self.broadcasts.subscribe(ctx.guild, destination, ctx.author.id)
        await ctx.send(
            f"Official Aestron updates will be sent to {destination.mention}.",
            ephemeral=True,
        )

    @updates_prefix.command(
        name="unsubscribe",
        brief="Stop official update announcements in this server.",
        description="Disable future Aestron release and service-status announcements.",
        usage="",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.cooldown(1, 20, commands.BucketType.guild)
    async def updates_unsubscribe_prefix(self, ctx: commands.Context) -> None:
        """Unsubscribe through a prefix command."""
        await self.broadcasts.unsubscribe(ctx.guild.id)
        await ctx.send("This server is unsubscribed from bot updates.", ephemeral=True)

    @updates_prefix.command(
        name="status",
        brief="Show this server's update-announcement destination.",
        description="Show whether updates are enabled and validate their destination.",
        usage="",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def updates_status_prefix(self, ctx: commands.Context) -> None:
        """Show subscription status through a prefix command."""
        embed = await self.broadcasts.subscription_embed(ctx.guild)
        await ctx.send(embed=embed, ephemeral=True)

    @updates.command(
        name="subscribe",
        description="Subscribe a channel to official Aestron updates.",
    )
    @app_commands.describe(
        channel="Destination text or announcement channel; defaults to this channel."
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 20, key=lambda interaction: interaction.guild_id)
    async def updates_subscribe(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Subscribe the server after validating an explicit destination."""
        await interaction.response.defer(ephemeral=True)
        destination = channel or interaction.channel
        if not isinstance(destination, discord.TextChannel):
            raise commands.BadArgument("Choose a text or announcement channel.")
        guild = cast(discord.Guild, interaction.guild)
        await self.broadcasts.subscribe(guild, destination, interaction.user.id)
        await interaction.followup.send(
            f"Official Aestron updates will be sent to {destination.mention}.",
            ephemeral=True,
        )

    @updates.command(
        name="unsubscribe",
        description="Stop official Aestron updates in this server.",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 20, key=lambda interaction: interaction.guild_id)
    async def updates_unsubscribe(self, interaction: discord.Interaction) -> None:
        """Disable the server subscription without deleting its audit row."""
        await interaction.response.defer(ephemeral=True)
        await self.broadcasts.unsubscribe(cast(discord.Guild, interaction.guild).id)
        await interaction.followup.send(
            "This server is unsubscribed from bot updates.", ephemeral=True
        )

    @updates.command(
        name="status",
        description="Show this server's update subscription.",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def updates_status(self, interaction: discord.Interaction) -> None:
        """Show the private subscription status."""
        guild = cast(discord.Guild, interaction.guild)
        await interaction.response.send_message(
            embed=await self.broadcasts.subscription_embed(guild),
            ephemeral=True,
        )

    @botadmin.command(
        name="activity",
        description="Export private activity status for every current guild.",
    )
    @app_commands.describe(window="Time window used to classify a guild as active.")
    @app_commands.choices(
        window=[
            app_commands.Choice(name="Last 24 hours", value="24h"),
            app_commands.Choice(name="Last 7 days", value="7d"),
            app_commands.Choice(name="Last 30 days", value="30d"),
        ]
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.check(_owner_only)
    async def guild_activity(
        self,
        interaction: discord.Interaction,
        window: app_commands.Choice[str] | None = None,
    ) -> None:
        """Return owner-only activity categories and a complete CSV export."""
        windows = {
            "24h": (timedelta(hours=24), "24 hours"),
            "7d": (timedelta(days=7), "7 days"),
            "30d": (timedelta(days=30), "30 days"),
        }
        await interaction.response.defer(ephemeral=True)
        selected_window, label = windows[window.value if window else "24h"]
        embed, file = await self.activity.report(selected_window, label)
        await interaction.followup.send(embed=embed, file=file, ephemeral=True)

    @botadmin.command(
        name="broadcast",
        description="Preview an update for every subscribed guild.",
    )
    @app_commands.describe(
        title="Short release or incident title.",
        summary="Public summary shown at the top of the announcement.",
        details="Optional bounded list of changes or incident details.",
        status="Current public service status.",
        include_stats="Include uptime, latency, and bot guild count.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.check(_owner_only)
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.user.id)
    async def create_broadcast(
        self,
        interaction: discord.Interaction,
        title: app_commands.Range[str, 1, 100],
        summary: app_commands.Range[str, 1, 1000],
        status: BroadcastStatus = "operational",
        details: app_commands.Range[str, 1, 1000] | None = None,
        include_stats: bool = False,
    ) -> None:
        """Create a private preview without sending until it is confirmed."""
        await interaction.response.defer(ephemeral=True)
        recipient_count = await self.broadcasts.recipient_count()
        if not recipient_count:
            await interaction.followup.send(
                "No guild has subscribed yet. A manager must run `/updates subscribe`.",
                ephemeral=True,
            )
            return
        draft = BroadcastDraft(
            title=title.strip(),
            summary=summary.strip(),
            details=details.strip() if details else None,
            status=status,
            include_stats=include_stats,
            created_by=interaction.user.id,
        )
        preview = self.broadcasts.embed(draft)
        preview.set_author(name=f"PREVIEW · {recipient_count} subscribed guild(s)")
        view = BroadcastConfirmationView(self.broadcasts, draft, recipient_count)
        view.message = await interaction.followup.send(
            embed=preview,
            view=view,
            ephemeral=True,
            wait=True,
        )

    @botadmin.command(
        name="broadcasts",
        description="Show recent update delivery results.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.check(_owner_only)
    async def broadcast_history(self, interaction: discord.Interaction) -> None:
        """Show recent broadcasts and their persisted delivery totals."""
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            embed=await self.broadcasts.history_embed(),
            ephemeral=True,
        )
