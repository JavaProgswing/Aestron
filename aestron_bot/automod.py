"""Consistent configuration for Aestron's channel auto-moderation filters."""

from __future__ import annotations

import collections
import logging
import re
import time
from datetime import timedelta

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

LOGGER = logging.getLogger(__name__)
LINK_PATTERN = re.compile(
    r"(?:https?://|www\.|discord(?:app)?\.(?:com/invite|gg)/)\S+",
    re.IGNORECASE,
)
SPAM_MESSAGES = 6
SPAM_WINDOW_SECONDS = 7
ACTION_TIMEOUT_MINUTES = 5
FEATURE_TABLES = {
    "spam": "spamchannels",
    "links": "linkchannels",
    "profanity": "profanechannels",
}
FEATURE_QUERIES = {
    "spam": (
        "SELECT EXISTS(SELECT 1 FROM spamchannels WHERE channelid = $1)",
        "INSERT INTO spamchannels (channelid) VALUES ($1)",
        "DELETE FROM spamchannels WHERE channelid = $1",
    ),
    "links": (
        "SELECT EXISTS(SELECT 1 FROM linkchannels WHERE channelid = $1)",
        "INSERT INTO linkchannels (channelid) VALUES ($1)",
        "DELETE FROM linkchannels WHERE channelid = $1",
    ),
    "profanity": (
        "SELECT EXISTS(SELECT 1 FROM profanechannels WHERE channelid = $1)",
        "INSERT INTO profanechannels (channelid) VALUES ($1)",
        "DELETE FROM profanechannels WHERE channelid = $1",
    ),
}


class AutoMod(commands.Cog):
    """Configure spam, link, and profanity enforcement per text channel."""

    automod = app_commands.Group(
        name="automod", description="Configure channel auto-moderation."
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot used for database configuration and audit events."""
        self.bot = bot
        self._state_cache: dict[int, tuple[float, dict[str, bool]]] = {}
        self._message_windows: dict[tuple[int, int, int], collections.deque[float]] = {}

    async def cog_load(self) -> None:
        """Ensure the legacy-compatible channel feature tables exist."""
        if not self.bot.database.connected:
            return
        async with self.bot.database.pool.acquire() as connection:
            for table in FEATURE_TABLES.values():
                await connection.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} (channelid BIGINT PRIMARY KEY)"
                )

    @staticmethod
    def _table(feature: str) -> str:
        try:
            return FEATURE_TABLES[feature]
        except KeyError as error:
            raise commands.BadArgument(
                "Feature must be `spam`, `links`, or `profanity`."
            ) from error

    async def _enabled(self, channel_id: int, feature: str) -> bool:
        return (await self._states(channel_id))[feature]

    async def _states(self, channel_id: int) -> dict[str, bool]:
        """Return all filter states with a short cache to avoid per-message churn."""
        cached = self._state_cache.get(channel_id)
        now = time.monotonic()
        if cached and cached[0] > now:
            return cached[1]
        async with self.bot.database.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT "
                "EXISTS(SELECT 1 FROM spamchannels WHERE channelid = $1) AS spam, "
                "EXISTS(SELECT 1 FROM linkchannels WHERE channelid = $1) AS links, "
                "EXISTS(SELECT 1 FROM profanechannels WHERE channelid = $1) "
                "AS profanity",
                channel_id,
            )
        states = {
            feature: bool(row[feature]) if row is not None else False
            for feature in FEATURE_TABLES
        }
        self._state_cache[channel_id] = (now + 30, states)
        return states

    async def _set(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        feature: str,
        enabled: bool,
        actor: discord.abc.User,
    ) -> None:
        if channel.guild.id != guild.id:
            raise commands.BadArgument("Choose a text channel in this server.")
        self._table(feature)
        select_query, insert_query, delete_query = FEATURE_QUERIES[feature]
        async with self.bot.database.pool.acquire() as connection:
            if enabled:
                exists = await connection.fetchval(select_query, channel.id)
                if not exists:
                    await connection.execute(insert_query, channel.id)
            else:
                await connection.execute(delete_query, channel.id)
        self._state_cache.pop(channel.id, None)
        audit_logging = self.bot.get_cog("AuditLogging")
        if audit_logging is not None:
            try:
                await audit_logging.dispatch(
                    guild,
                    kind="automod_config",
                    title="AutoMod configuration changed",
                    target=f"{channel.mention} (`{channel.id}`)",
                    target_id=channel.id,
                    actor_override=actor,
                    reason_override=f"{feature} {'enabled' if enabled else 'disabled'}",
                    color=discord.Color.orange(),
                )
            except Exception:
                LOGGER.exception(
                    "Could not log AutoMod configuration guild=%s", guild.id
                )

    async def status_embed(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Embed:
        """Show enabled filters and permission readiness for one channel."""
        states = {
            feature: await self._enabled(channel.id, feature)
            for feature in FEATURE_TABLES
        }
        bot_member = guild.me
        permissions = channel.permissions_for(bot_member) if bot_member else None
        missing = [
            name
            for name in (
                "view_channel",
                "send_messages",
                "manage_messages",
                "moderate_members",
            )
            if permissions is None or not getattr(permissions, name, False)
        ]
        embed = discord.Embed(
            title=f"AutoMod · #{channel.name}",
            description=(
                "Filters act on regular members; members with Manage Server and bot "
                "staff are exempt."
            ),
            color=0x5865F2,
        )
        for feature, enabled in states.items():
            detail = "✅ Enabled" if enabled else "➖ Disabled"
            if (
                feature == "profanity"
                and enabled
                and not getattr(self.bot, "perspective_api_key", None)
            ):
                detail = "⚠️ Enabled, but `GCOM_TOKEN` is unavailable"
            embed.add_field(name=feature.title(), value=detail)
        embed.add_field(
            name="Permission health",
            value="Ready" if not missing else "Missing: " + ", ".join(missing),
            inline=False,
        )
        embed.set_footer(text="Use /automod set to change a filter")
        return embed

    @staticmethod
    def _exempt(message: discord.Message) -> bool:
        """Return whether a member may bypass channel filters."""
        member = message.author
        return (
            not isinstance(member, discord.Member)
            or member.bot
            or member == message.guild.owner
            or member.guild_permissions.manage_guild
        )

    def _is_spam(self, message: discord.Message) -> bool:
        """Track a bounded seven-second message window per member and channel."""
        key = (message.guild.id, message.channel.id, message.author.id)
        now = time.monotonic()
        window = self._message_windows.setdefault(key, collections.deque())
        while window and window[0] <= now - SPAM_WINDOW_SECONDS:
            window.popleft()
        window.append(now)
        if len(window) < SPAM_MESSAGES:
            return False
        window.clear()
        if len(self._message_windows) > 10_000:
            self._message_windows = {
                item_key: timestamps
                for item_key, timestamps in self._message_windows.items()
                if timestamps and timestamps[-1] > now - SPAM_WINDOW_SECONDS
            }
        return True

    async def _profanity_score(self, content: str) -> float | None:
        """Return Perspective's profanity score without storing message content."""
        api_key = getattr(self.bot, "perspective_api_key", None)
        session = getattr(self.bot, "session", None)
        if not api_key or session is None or not content.strip():
            return None
        payload = {
            "comment": {"text": content[:3000]},
            "requestedAttributes": {"PROFANITY": {}},
            "doNotStore": True,
        }
        try:
            async with session.post(
                "https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze",
                params={"key": api_key},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as response:
                if response.status != 200:
                    LOGGER.warning(
                        "Perspective API returned status=%s", response.status
                    )
                    return None
                result = await response.json()
        except (aiohttp.ClientError, TimeoutError):
            LOGGER.warning("Perspective API request failed", exc_info=True)
            return None
        try:
            return float(
                result["attributeScores"]["PROFANITY"]["summaryScore"]["value"]
            )
        except (KeyError, TypeError, ValueError):
            LOGGER.warning("Perspective API returned an unexpected response")
            return None

    async def _notify(self, message: discord.Message, reason: str) -> None:
        notice = (
            f"Your message in **{message.guild.name}** was removed by AutoMod "
            f"for **{reason}**. A {ACTION_TIMEOUT_MINUTES}-minute timeout may "
            "also have been applied."
        )
        try:
            await message.author.send(notice)
            return
        except (discord.Forbidden, discord.HTTPException):
            pass
        try:
            await message.channel.send(
                f"{message.author.mention} {notice}",
                delete_after=10,
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.warning(
                "Could not notify AutoMod target guild=%s member=%s",
                message.guild.id,
                message.author.id,
            )

    async def _enforce(self, message: discord.Message, reason: str) -> None:
        """Delete the message, apply a native timeout, notify, and record the action."""
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            LOGGER.warning(
                "Could not delete AutoMod message guild=%s channel=%s message=%s",
                message.guild.id,
                message.channel.id,
                message.id,
            )
        member = message.author
        bot_member = message.guild.me
        if (
            isinstance(member, discord.Member)
            and bot_member is not None
            and bot_member.guild_permissions.moderate_members
            and member.top_role < bot_member.top_role
        ):
            try:
                await member.timeout(
                    discord.utils.utcnow() + timedelta(minutes=ACTION_TIMEOUT_MINUTES),
                    reason=f"Aestron AutoMod: {reason}",
                )
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.warning(
                    "Could not timeout AutoMod target guild=%s member=%s",
                    message.guild.id,
                    member.id,
                )
        await self._notify(message, reason)
        audit_logging = self.bot.get_cog("AuditLogging")
        if audit_logging is not None:
            try:
                await audit_logging.dispatch(
                    message.guild,
                    kind="automod_action",
                    title="AutoMod action",
                    target=f"{member.mention} (`{member.id}`)",
                    target_id=member.id,
                    actor_override=self.bot.user,
                    reason_override=f"{reason} in #{message.channel}",
                    color=discord.Color.orange(),
                )
            except Exception:
                LOGGER.exception(
                    "Could not log AutoMod action guild=%s", message.guild.id
                )

    async def _check_message(
        self, message: discord.Message, *, edited: bool = False
    ) -> None:
        """Evaluate one new or edited guild message against configured filters."""
        if (
            message.guild is None
            or not isinstance(message.channel, discord.TextChannel)
            or self._exempt(message)
            or not self.bot.database.connected
        ):
            return
        states = await self._states(message.channel.id)
        if states["links"] and LINK_PATTERN.search(message.content):
            await self._enforce(message, "a blocked link or invite")
            return
        if not edited and states["spam"] and self._is_spam(message):
            await self._enforce(
                message,
                f"message spam ({SPAM_MESSAGES} messages/{SPAM_WINDOW_SECONDS}s)",
            )
            return
        if states["profanity"]:
            score = await self._profanity_score(message.content)
            if score is not None and score >= 0.45:
                await self._enforce(message, "profanity")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Enforce configured filters on new messages."""
        await self._check_message(message)

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        """Recheck edited content without counting the edit as spam."""
        if before.content != after.content:
            await self._check_message(after, edited=True)

    async def _prefix_set(
        self,
        ctx: commands.Context,
        feature: str,
        enabled: bool,
        channel: discord.TextChannel | None,
    ) -> None:
        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel):
            raise commands.BadArgument("Choose a text channel.")
        await self._set(ctx.guild, target, feature, enabled, ctx.author)
        await ctx.send(
            f"{feature.title()} filtering is now "
            f"**{'enabled' if enabled else 'disabled'}** in {target.mention}.",
            ephemeral=True,
        )

    @commands.group(
        name="automod",
        invoke_without_command=True,
        brief="Configure or inspect channel AutoMod.",
        description=(
            "Configure spam, link, and profanity filters for a text channel. Run "
            "without a subcommand to show the current channel's status."
        ),
        usage="[set|status]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def automod_prefix(self, ctx: commands.Context) -> None:
        """Show the current channel status when no subcommand is supplied."""
        if not isinstance(ctx.channel, discord.TextChannel):
            raise commands.BadArgument("Use this command in a text channel.")
        await ctx.send(
            embed=await self.status_embed(ctx.guild, ctx.channel), ephemeral=True
        )

    @automod_prefix.command(
        name="set",
        brief="Enable or disable one AutoMod filter.",
        description=(
            "Enable or disable `spam`, `links`, or `profanity` filtering in the "
            "selected or current text channel."
        ),
        usage="<spam|links|profanity> <true|false> [channel]",
    )
    @commands.cooldown(2, 10, commands.BucketType.guild)
    async def prefix_set(
        self,
        ctx: commands.Context,
        feature: str,
        enabled: bool,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Configure one filter through a canonical prefix subcommand."""
        feature = feature.casefold()
        self._table(feature)
        await self._prefix_set(ctx, feature, enabled, channel)

    @automod_prefix.command(
        name="status",
        brief="Show AutoMod filters and permission health.",
        description=(
            "Show spam, link, profanity, integration, and bot-permission health "
            "for the selected or current text channel."
        ),
        usage="[channel]",
    )
    @commands.cooldown(2, 10, commands.BucketType.guild)
    async def prefix_status(
        self, ctx: commands.Context, channel: discord.TextChannel | None = None
    ) -> None:
        """Show AutoMod health through a canonical prefix subcommand."""
        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel):
            raise commands.BadArgument("Choose a text channel.")
        await ctx.send(embed=await self.status_embed(ctx.guild, target), ephemeral=True)

    @automod.command(name="set", description="Enable or disable a channel filter.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(2, 10, key=lambda interaction: interaction.guild_id)
    @app_commands.choices(
        feature=[
            app_commands.Choice(name="Spam", value="spam"),
            app_commands.Choice(name="Links and invites", value="links"),
            app_commands.Choice(name="Profanity", value="profanity"),
        ]
    )
    async def slash_set(
        self,
        interaction: discord.Interaction,
        feature: app_commands.Choice[str],
        enabled: bool,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Configure AutoMod through slash commands."""
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                "Choose a text channel.", ephemeral=True
            )
            return
        await self._set(
            interaction.guild, target, feature.value, enabled, interaction.user
        )
        await interaction.response.send_message(
            f"{feature.name} is now **{'enabled' if enabled else 'disabled'}** "
            f"in {target.mention}.",
            ephemeral=True,
        )

    @automod.command(name="status", description="Show channel AutoMod health.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(2, 10, key=lambda interaction: interaction.guild_id)
    async def slash_status(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Show AutoMod health through slash commands."""
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                "Choose a text channel.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=await self.status_embed(interaction.guild, target), ephemeral=True
        )
