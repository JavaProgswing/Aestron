"""Consistent configuration for Aestron's channel auto-moderation filters."""

from __future__ import annotations

import collections
import logging
import re
import time
from dataclasses import dataclass
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
FEATURE_WRITE_QUERIES = {
    "spam": (
        "INSERT INTO spamchannels (channelid) VALUES ($1) "
        "ON CONFLICT (channelid) DO NOTHING",
        "DELETE FROM spamchannels WHERE channelid = $1",
    ),
    "links": (
        "INSERT INTO linkchannels (channelid) VALUES ($1) "
        "ON CONFLICT (channelid) DO NOTHING",
        "DELETE FROM linkchannels WHERE channelid = $1",
    ),
    "profanity": (
        "INSERT INTO profanechannels (channelid) VALUES ($1) "
        "ON CONFLICT (channelid) DO NOTHING",
        "DELETE FROM profanechannels WHERE channelid = $1",
    ),
}


@dataclass(frozen=True, slots=True)
class AutoModPolicy:
    """Resolved per-channel filters and enforcement thresholds."""

    spam: bool = False
    links: bool = False
    profanity: bool = False
    spam_messages: int = SPAM_MESSAGES
    spam_window_seconds: int = SPAM_WINDOW_SECONDS
    timeout_seconds: int = ACTION_TIMEOUT_MINUTES * 60
    profanity_threshold: float = 0.45

    @property
    def states(self) -> dict[str, bool]:
        """Return filter switches keyed by their public feature names."""
        return {
            "spam": self.spam,
            "links": self.links,
            "profanity": self.profanity,
        }


class AutoModChannelSelect(discord.ui.ChannelSelect):
    """Select message-capable channels that should receive one policy."""

    def __init__(self, current_channel: discord.abc.GuildChannel) -> None:
        """Default the multi-channel selector to the invoking channel."""
        super().__init__(
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.news,
                discord.ChannelType.forum,
                discord.ChannelType.media,
                discord.ChannelType.voice,
                discord.ChannelType.stage_voice,
            ],
            placeholder="Choose up to 25 channels",
            min_values=1,
            max_values=25,
            default_values=[discord.SelectDefaultValue.from_channel(current_channel)],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Store the current selection and refresh its private preview."""
        view = self.view
        if not isinstance(view, AutoModSetupView):
            return
        view.channel_ids = {channel.id for channel in self.values}
        await interaction.response.edit_message(embed=view.embed(), view=view)


class AutoModSetupView(discord.ui.View):
    """Ephemeral bulk AutoMod setup owned by one administrator."""

    def __init__(
        self,
        *,
        owner_id: int,
        current_channel: discord.abc.GuildChannel,
        policy: AutoModPolicy,
    ) -> None:
        """Build a five-minute setup session for one administrator."""
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.channel_ids = {current_channel.id}
        self.policy = policy
        self.add_item(AutoModChannelSelect(current_channel))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Reject attempts to modify another administrator's setup."""
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "Only the administrator who opened this setup can use it.", ephemeral=True
        )
        return False

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        """Acknowledge setup failures instead of leaving a timed-out interaction."""
        LOGGER.error(
            "AutoMod setup interaction failed guild=%s item=%s",
            interaction.guild_id,
            getattr(item, "custom_id", None),
            exc_info=(type(error), error, error.__traceback__),
        )
        message = (
            str(error)
            if isinstance(error, (commands.CommandError, discord.HTTPException))
            else "AutoMod setup failed unexpectedly. Check the bot logs and permissions."
        )
        if interaction.response.is_done():
            await interaction.followup.send(message[:1900], ephemeral=True)
        else:
            await interaction.response.send_message(message[:1900], ephemeral=True)

    def embed(self) -> discord.Embed:
        """Render the selected scope and complete policy before applying it."""
        enabled = [name.title() for name, state in self.policy.states.items() if state]
        embed = discord.Embed(
            title="AutoMod bulk setup",
            description=(
                f"Selected **{len(self.channel_ids)}** channel(s). Choose channels "
                "above, review the policy, then apply it."
            ),
            color=0x5865F2,
        )
        embed.add_field(
            name="Filters", value=", ".join(enabled) or "No filters enabled"
        )
        embed.add_field(
            name="Spam",
            value=(
                f"{self.policy.spam_messages} messages in "
                f"{self.policy.spam_window_seconds}s"
            ),
        )
        embed.add_field(
            name="Action",
            value=(
                f"{self.policy.timeout_seconds // 60} minute timeout"
                if self.policy.timeout_seconds
                else "Delete and warn only"
            ),
        )
        embed.add_field(
            name="Profanity threshold",
            value=f"{self.policy.profanity_threshold:.0%}",
        )
        embed.set_footer(
            text="This configuration is persistent and can be changed later"
        )
        return embed

    @discord.ui.button(label="Apply policy", style=discord.ButtonStyle.success, row=1)
    async def apply(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Persist the policy for every selected channel."""
        cog = interaction.client.get_cog("AutoMod")
        if cog is None or interaction.guild is None:
            await interaction.response.send_message(
                "AutoMod is unavailable right now.", ephemeral=True
            )
            return
        channels = [
            interaction.guild.get_channel(channel_id) for channel_id in self.channel_ids
        ]
        guild_channels = [
            channel
            for channel in channels
            if isinstance(channel, discord.abc.GuildChannel)
        ]
        await interaction.response.defer(ephemeral=True, thinking=True)
        await cog.configure_channels(
            interaction.guild, guild_channels, self.policy, interaction.user
        )
        self.stop()
        await interaction.edit_original_response(
            content=f"AutoMod policy applied to {len(guild_channels)} channel(s).",
            embed=None,
            view=None,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Close the setup without changing persistent configuration."""
        self.stop()
        await interaction.response.edit_message(
            content="AutoMod setup cancelled.", embed=None, view=None
        )


class AutoMod(commands.Cog):
    """Configure spam, link, and profanity enforcement per text channel."""

    automod = app_commands.Group(
        name="automod", description="Configure channel auto-moderation."
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot used for database configuration and audit events."""
        self.bot = bot
        self._state_cache: dict[int, tuple[float, AutoModPolicy]] = {}
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
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS automod_channel_settings (
                    channel_id BIGINT PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    spam_messages SMALLINT NOT NULL DEFAULT 6
                        CHECK (spam_messages BETWEEN 3 AND 20),
                    spam_window_seconds SMALLINT NOT NULL DEFAULT 7
                        CHECK (spam_window_seconds BETWEEN 3 AND 60),
                    timeout_seconds INTEGER NOT NULL DEFAULT 300
                        CHECK (timeout_seconds BETWEEN 0 AND 86400),
                    profanity_threshold REAL NOT NULL DEFAULT 0.45
                        CHECK (profanity_threshold BETWEEN 0.1 AND 1.0),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
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
        return (await self._policy(channel_id)).states[feature]

    async def _states(self, channel_id: int) -> dict[str, bool]:
        """Return all feature states for compatibility with status consumers."""
        return (await self._policy(channel_id)).states

    async def _policy(self, channel_id: int) -> AutoModPolicy:
        """Return one complete policy with a short per-channel cache."""
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
                "AS profanity, settings.spam_messages, "
                "settings.spam_window_seconds, settings.timeout_seconds, "
                "settings.profanity_threshold FROM (SELECT $1::BIGINT AS channel_id) "
                "selected LEFT JOIN automod_channel_settings settings "
                "ON settings.channel_id = selected.channel_id",
                channel_id,
            )
        policy = AutoModPolicy(
            spam=bool(row["spam"]) if row else False,
            links=bool(row["links"]) if row else False,
            profanity=bool(row["profanity"]) if row else False,
            spam_messages=int(row["spam_messages"] or SPAM_MESSAGES)
            if row
            else SPAM_MESSAGES,
            spam_window_seconds=(
                int(row["spam_window_seconds"] or SPAM_WINDOW_SECONDS)
                if row
                else SPAM_WINDOW_SECONDS
            ),
            timeout_seconds=(
                int(row["timeout_seconds"])
                if row and row["timeout_seconds"] is not None
                else ACTION_TIMEOUT_MINUTES * 60
            ),
            profanity_threshold=(
                float(row["profanity_threshold"] or 0.45) if row else 0.45
            ),
        )
        self._state_cache[channel_id] = (now + 30, policy)
        return policy

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
            await connection.execute(
                "INSERT INTO automod_channel_settings (channel_id, guild_id) "
                "VALUES ($1, $2) ON CONFLICT (channel_id) DO NOTHING",
                channel.id,
                guild.id,
            )
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

    async def configure_channels(
        self,
        guild: discord.Guild,
        channels: list[discord.abc.GuildChannel],
        policy: AutoModPolicy,
        actor: discord.abc.User,
    ) -> None:
        """Apply one validated policy to several channels in one transaction."""
        if not channels:
            raise commands.BadArgument("Select at least one supported server channel.")
        if any(channel.guild.id != guild.id for channel in channels):
            raise commands.BadArgument("Every channel must belong to this server.")
        if not (
            3 <= policy.spam_messages <= 20
            and 3 <= policy.spam_window_seconds <= 60
            and 0 <= policy.timeout_seconds <= 86_400
            and 0.1 <= policy.profanity_threshold <= 1.0
        ):
            raise commands.BadArgument("One or more AutoMod policy values are invalid.")
        async with self.bot.database.pool.acquire() as connection:
            async with connection.transaction():
                for channel in channels:
                    await connection.execute(
                        "INSERT INTO automod_channel_settings "
                        "(channel_id, guild_id, spam_messages, spam_window_seconds, "
                        "timeout_seconds, profanity_threshold) "
                        "VALUES ($1, $2, $3, $4, $5, $6) "
                        "ON CONFLICT (channel_id) DO UPDATE SET "
                        "guild_id = EXCLUDED.guild_id, "
                        "spam_messages = EXCLUDED.spam_messages, "
                        "spam_window_seconds = EXCLUDED.spam_window_seconds, "
                        "timeout_seconds = EXCLUDED.timeout_seconds, "
                        "profanity_threshold = EXCLUDED.profanity_threshold, "
                        "updated_at = NOW()",
                        channel.id,
                        guild.id,
                        policy.spam_messages,
                        policy.spam_window_seconds,
                        policy.timeout_seconds,
                        policy.profanity_threshold,
                    )
                    for feature, enabled in policy.states.items():
                        self._table(feature)
                        insert_query, delete_query = FEATURE_WRITE_QUERIES[feature]
                        if enabled:
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
                    title="Bulk AutoMod policy applied",
                    target=", ".join(channel.mention for channel in channels)[:1000],
                    actor_override=actor,
                    reason_override=(
                        f"Filters: {', '.join(name for name, enabled in policy.states.items() if enabled) or 'none'}; "
                        f"spam={policy.spam_messages}/{policy.spam_window_seconds}s; "
                        f"timeout={policy.timeout_seconds}s"
                    ),
                    color=discord.Color.orange(),
                )
            except Exception:
                LOGGER.exception("Could not log bulk AutoMod setup guild=%s", guild.id)

    async def status_embed(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Embed:
        """Show enabled filters and permission readiness for one channel."""
        policy = await self._policy(channel.id)
        states = policy.states
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
        embed.add_field(
            name="Policy",
            value=(
                f"Spam: **{policy.spam_messages} messages/{policy.spam_window_seconds}s** · "
                f"Timeout: **{policy.timeout_seconds // 60}m** · "
                f"Profanity: **{policy.profanity_threshold:.0%}**"
            ),
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

    def _is_spam(
        self, message: discord.Message, policy: AutoModPolicy = AutoModPolicy()
    ) -> bool:
        """Track a bounded per-policy message window per member and channel."""
        key = (message.guild.id, message.channel.id, message.author.id)
        now = time.monotonic()
        window = self._message_windows.setdefault(key, collections.deque())
        while window and window[0] <= now - policy.spam_window_seconds:
            window.popleft()
        window.append(now)
        if len(window) < policy.spam_messages:
            return False
        window.clear()
        if len(self._message_windows) > 10_000:
            self._message_windows = {
                item_key: timestamps
                for item_key, timestamps in self._message_windows.items()
                if timestamps and timestamps[-1] > now - policy.spam_window_seconds
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

    async def _notify(
        self, message: discord.Message, reason: str, *, timeout_seconds: int
    ) -> None:
        notice = (
            f"Your message in **{message.guild.name}** was removed by AutoMod "
            f"for **{reason}**."
        )
        if timeout_seconds:
            notice += (
                f" A {timeout_seconds // 60}-minute timeout may also have been applied."
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

    async def _enforce(
        self, message: discord.Message, reason: str, *, timeout_seconds: int
    ) -> None:
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
            and timeout_seconds > 0
            and bot_member is not None
            and bot_member.guild_permissions.moderate_members
            and member.top_role < bot_member.top_role
        ):
            try:
                await member.timeout(
                    discord.utils.utcnow() + timedelta(seconds=timeout_seconds),
                    reason=f"Aestron AutoMod: {reason}",
                )
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.warning(
                    "Could not timeout AutoMod target guild=%s member=%s",
                    message.guild.id,
                    member.id,
                )
        await self._notify(message, reason, timeout_seconds=timeout_seconds)
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
        channel = message.channel
        policy_channel = (
            channel.parent if isinstance(channel, discord.Thread) else channel
        )
        if (
            message.guild is None
            or not isinstance(policy_channel, discord.abc.GuildChannel)
            or self._exempt(message)
            or not self.bot.database.connected
        ):
            return
        policy = await self._policy(policy_channel.id)
        states = policy.states
        if states["links"] and LINK_PATTERN.search(message.content):
            await self._enforce(
                message,
                "a blocked link or invite",
                timeout_seconds=policy.timeout_seconds,
            )
            return
        if not edited and states["spam"] and self._is_spam(message, policy):
            await self._enforce(
                message,
                f"message spam ({policy.spam_messages} messages/"
                f"{policy.spam_window_seconds}s)",
                timeout_seconds=policy.timeout_seconds,
            )
            return
        if states["profanity"]:
            score = await self._profanity_score(message.content)
            if score is not None and score >= policy.profanity_threshold:
                await self._enforce(
                    message,
                    "profanity",
                    timeout_seconds=policy.timeout_seconds,
                )

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

    @automod.command(
        name="setup", description="Configure one policy across several channels."
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 20, key=lambda interaction: interaction.guild_id)
    async def slash_setup(
        self,
        interaction: discord.Interaction,
        spam: bool = True,
        links: bool = True,
        profanity: bool = False,
        spam_messages: app_commands.Range[int, 3, 20] = SPAM_MESSAGES,
        spam_window_seconds: app_commands.Range[int, 3, 60] = SPAM_WINDOW_SECONDS,
        timeout_minutes: app_commands.Range[int, 0, 1440] = ACTION_TIMEOUT_MINUTES,
        profanity_threshold: app_commands.Range[float, 0.1, 1.0] = 0.45,
    ) -> None:
        """Open a channel selector for one complete, persistent policy."""
        if interaction.guild is None or not isinstance(
            interaction.channel, discord.abc.GuildChannel
        ):
            await interaction.response.send_message(
                "Run this setup inside a server channel.", ephemeral=True
            )
            return
        policy = AutoModPolicy(
            spam=spam,
            links=links,
            profanity=profanity,
            spam_messages=spam_messages,
            spam_window_seconds=spam_window_seconds,
            timeout_seconds=timeout_minutes * 60,
            profanity_threshold=profanity_threshold,
        )
        view = AutoModSetupView(
            owner_id=interaction.user.id,
            current_channel=interaction.channel,
            policy=policy,
        )
        await interaction.response.send_message(
            embed=view.embed(), view=view, ephemeral=True
        )

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
