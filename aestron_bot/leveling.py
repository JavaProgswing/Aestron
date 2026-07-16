"""Efficient, channel-configurable guild leveling."""

from __future__ import annotations

import contextlib
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

LOGGER = logging.getLogger(__name__)
DEFAULT_MESSAGES_PER_LEVEL = 25


class Leveling(commands.Cog):
    """Track bounded message activity and show rank leaderboards."""

    leveling = app_commands.Group(
        name="leveling", description="Configure and inspect server leveling."
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize a per-member XP cooldown and channel-setting cache."""
        self.bot = bot
        self._last_xp: dict[tuple[int, int], float] = {}
        self._settings_cache: dict[int, tuple[float, bool, int]] = {}

    async def cog_load(self) -> None:
        """Ensure legacy-compatible leveling tables exist."""
        if not self.bot.database.connected:
            return
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS levelsettings ("
                "channelid BIGINT PRIMARY KEY, setting BOOLEAN NOT NULL DEFAULT FALSE)"
            )
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS levelconfig ("
                "channelid BIGINT PRIMARY KEY, messagecount INTEGER NOT NULL DEFAULT 25)"
            )
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS leveling ("
                "guildid BIGINT NOT NULL, memberid BIGINT NOT NULL, "
                "messagecount INTEGER NOT NULL DEFAULT 0, "
                "PRIMARY KEY (guildid, memberid))"
            )

    async def _settings(self, channel_id: int) -> tuple[bool, int]:
        cached = self._settings_cache.get(channel_id)
        now = time.monotonic()
        if cached and cached[0] > now:
            return cached[1], cached[2]
        async with self.bot.database.pool.acquire() as connection:
            enabled = await connection.fetchval(
                "SELECT setting FROM levelsettings WHERE channelid = $1", channel_id
            )
            required = await connection.fetchval(
                "SELECT messagecount FROM levelconfig WHERE channelid = $1", channel_id
            )
        result = bool(enabled), int(required or DEFAULT_MESSAGES_PER_LEVEL)
        self._settings_cache[channel_id] = (now + 60, *result)
        return result

    async def _configure(
        self, channel_id: int, *, enabled: bool, messages_per_level: int
    ) -> None:
        async with self.bot.database.pool.acquire() as connection:
            setting_exists = await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM levelsettings WHERE channelid = $1)",
                channel_id,
            )
            if setting_exists:
                await connection.execute(
                    "UPDATE levelsettings SET setting = $1 WHERE channelid = $2",
                    enabled,
                    channel_id,
                )
            else:
                await connection.execute(
                    "INSERT INTO levelsettings (channelid, setting) VALUES ($1, $2)",
                    channel_id,
                    enabled,
                )
            config_exists = await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM levelconfig WHERE channelid = $1)",
                channel_id,
            )
            if config_exists:
                await connection.execute(
                    "UPDATE levelconfig SET messagecount = $1 WHERE channelid = $2",
                    messages_per_level,
                    channel_id,
                )
            else:
                await connection.execute(
                    "INSERT INTO levelconfig (channelid, messagecount) VALUES ($1, $2)",
                    channel_id,
                    messages_per_level,
                )
        self._settings_cache.pop(channel_id, None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Award one message point at most every 15 seconds per member."""
        if (
            message.author.bot
            or message.guild is None
            or not isinstance(message.channel, discord.TextChannel)
            or not self.bot.database.connected
        ):
            return
        enabled, required = await self._settings(message.channel.id)
        if not enabled:
            return
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        if self._last_xp.get(key, 0) > now - 15:
            return
        self._last_xp[key] = now
        async with self.bot.database.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT messagecount FROM leveling WHERE guildid = $1 AND memberid = $2",
                message.guild.id,
                message.author.id,
            )
            old_count = int(row["messagecount"]) if row else 0
            new_count = old_count + 1
            if row:
                await connection.execute(
                    "UPDATE leveling SET messagecount = $1 "
                    "WHERE guildid = $2 AND memberid = $3",
                    new_count,
                    message.guild.id,
                    message.author.id,
                )
            else:
                await connection.execute(
                    "INSERT INTO leveling (guildid, memberid, messagecount) "
                    "VALUES ($1, $2, 1)",
                    message.guild.id,
                    message.author.id,
                )
        if new_count // required > old_count // required:
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await message.channel.send(
                    f"🎉 {message.author.mention} reached level **{new_count // required}**!",
                    allowed_mentions=discord.AllowedMentions(users=True),
                )

    async def rank_embed(
        self,
        guild: discord.Guild,
        member: discord.Member,
        channel_id: int,
    ) -> discord.Embed:
        """Build one member's rank without rendering temporary image files."""
        _, required = await self._settings(channel_id)
        async with self.bot.database.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT messagecount, (SELECT COUNT(*) + 1 FROM leveling higher "
                "WHERE higher.guildid = current.guildid "
                "AND higher.messagecount > current.messagecount) AS rank "
                "FROM leveling current WHERE guildid = $1 AND memberid = $2",
                guild.id,
                member.id,
            )
        count = int(row["messagecount"]) if row else 0
        rank = int(row["rank"]) if row else 0
        level = count // required
        progress = count % required
        filled = min(10, int((progress / required) * 10))
        bar = "▰" * filled + "▱" * (10 - filled)
        embed = discord.Embed(
            title=f"{member.display_name}'s level",
            description=f"`{bar}` {progress}/{required}",
            color=member.color if member.color.value else 0x5865F2,
        )
        embed.add_field(name="Level", value=str(level))
        embed.add_field(name="Rank", value=f"#{rank}" if rank else "Unranked")
        embed.add_field(name="Counted messages", value=str(count))
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Message points have a 15-second anti-spam cooldown")
        return embed

    async def leaderboard_embed(
        self, guild: discord.Guild, channel_id: int
    ) -> discord.Embed:
        """Build a top-ten leaderboard that also works with fewer than five users."""
        _, required = await self._settings(channel_id)
        async with self.bot.database.pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT memberid, messagecount FROM leveling WHERE guildid = $1 "
                "ORDER BY messagecount DESC, memberid ASC LIMIT 10",
                guild.id,
            )
        lines = []
        for index, row in enumerate(rows, start=1):
            member = guild.get_member(int(row["memberid"]))
            if member is None:
                continue
            count = int(row["messagecount"])
            lines.append(
                f"**{index}.** {member.mention} · level {count // required} · {count} messages"
            )
        return discord.Embed(
            title=f"{guild.name} leaderboard",
            description="\n".join(lines) or "No ranked members yet.",
            color=0xFEE75C,
        )

    @commands.cooldown(2, 10, commands.BucketType.member)
    @commands.hybrid_command(
        with_app_command=False,
        aliases=["rank", "levels"],
        brief="Show a member's level, progress, and server rank.",
        description="Show counted messages and progress using this channel's level target.",
        usage="[member]",
    )
    @commands.guild_only()
    async def level(
        self, ctx: commands.Context, member: discord.Member | None = None
    ) -> None:
        """Show a rank card through a prefix command."""
        await ctx.send(
            embed=await self.rank_embed(
                ctx.guild, member or ctx.author, ctx.channel.id
            ),
            ephemeral=True,
        )

    @commands.cooldown(1, 10, commands.BucketType.member)
    @commands.hybrid_command(
        with_app_command=False,
        aliases=["lb", "leaderboard"],
        brief="Show the top ten members by counted messages.",
        description="Show a text leaderboard that works even with fewer than five members.",
        usage="",
    )
    @commands.guild_only()
    async def levelrank(self, ctx: commands.Context) -> None:
        """Show the leaderboard through a prefix command."""
        await ctx.send(
            embed=await self.leaderboard_embed(ctx.guild, ctx.channel.id),
            ephemeral=True,
        )

    @commands.cooldown(2, 10, commands.BucketType.guild)
    @commands.hybrid_command(
        with_app_command=False,
        aliases=["leveltoggle", "togglelevel"],
        brief="Enable or disable leveling in one channel.",
        description="Set channel leveling explicitly, or omit enabled to toggle it.",
        usage="[channel] [enabled]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def levelsettings(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Configure channel leveling through a prefix command."""
        target = channel or ctx.channel
        current, required = await self._settings(target.id)
        new_value = not current if enabled is None else enabled
        await self._configure(target.id, enabled=new_value, messages_per_level=required)
        await ctx.send(
            f"Leveling is now **{'enabled' if new_value else 'disabled'}** in "
            f"{target.mention}.",
            ephemeral=True,
        )

    @commands.cooldown(2, 10, commands.BucketType.guild)
    @commands.hybrid_command(
        with_app_command=False,
        aliases=["messageconfig", "levelset", "messageperlevel"],
        brief="Set the counted messages required for one level.",
        description="Set a channel's level target from 20 to 10,000 counted messages.",
        usage="<messages_per_level> [channel]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def setlevelmessage(
        self,
        ctx: commands.Context,
        messages_per_level: commands.Range[int, 20, 10000],
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Set the level target through a prefix command."""
        target = channel or ctx.channel
        enabled, _ = await self._settings(target.id)
        await self._configure(
            target.id,
            enabled=enabled,
            messages_per_level=messages_per_level,
        )
        await ctx.send(
            f"{target.mention} now requires **{messages_per_level}** counted "
            "messages per level.",
            ephemeral=True,
        )

    @leveling.command(name="rank", description="Show a member's level and rank.")
    async def slash_rank(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        """Show a rank card through slash commands."""
        target = member or interaction.user
        if not isinstance(target, discord.Member):
            await interaction.response.send_message(
                "Use this command in a server.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=await self.rank_embed(
                interaction.guild, target, interaction.channel_id
            ),
            ephemeral=True,
        )

    @leveling.command(name="leaderboard", description="Show the top ten members.")
    async def slash_leaderboard(self, interaction: discord.Interaction) -> None:
        """Show the leaderboard through slash commands."""
        await interaction.response.send_message(
            embed=await self.leaderboard_embed(
                interaction.guild, interaction.channel_id
            )
        )

    @leveling.command(name="configure", description="Configure channel leveling.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(2, 10, key=lambda interaction: interaction.guild_id)
    async def slash_configure(
        self,
        interaction: discord.Interaction,
        enabled: bool,
        messages_per_level: app_commands.Range[int, 20, 10000] = 25,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Configure leveling through slash commands."""
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                "Choose a text channel.", ephemeral=True
            )
            return
        await self._configure(
            target.id,
            enabled=enabled,
            messages_per_level=messages_per_level,
        )
        await interaction.response.send_message(
            f"Leveling is **{'enabled' if enabled else 'disabled'}** in "
            f"{target.mention}; {messages_per_level} messages per level.",
            ephemeral=True,
        )
