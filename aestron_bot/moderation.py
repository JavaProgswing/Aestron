"""Validated moderation commands for discord.py 2.x."""

from __future__ import annotations

import contextlib
import json
import logging
import re
from datetime import timedelta

import discord
from discord.ext import commands

LOGGER = logging.getLogger(__name__)

_DURATION_PART = re.compile(r"(?P<value>\d+)(?P<unit>[smhdw])", re.IGNORECASE)
_DURATION_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_MAX_TIMEOUT_SECONDS = 28 * 86400


def parse_duration(value: str) -> timedelta:
    """Parse a compact duration such as ``30m`` or ``1d12h``."""
    compact = value.replace(" ", "")
    matches = list(_DURATION_PART.finditer(compact))
    if not matches or "".join(match.group(0) for match in matches) != compact:
        raise commands.BadArgument(
            "Invalid duration. Use values such as `30m`, `2h`, or `1d12h`."
        )
    seconds = sum(
        int(match.group("value")) * _DURATION_SECONDS[match.group("unit").lower()]
        for match in matches
    )
    if not 1 <= seconds <= _MAX_TIMEOUT_SECONDS:
        raise commands.BadArgument("Duration must be between 1 second and 28 days.")
    return timedelta(seconds=seconds)


def _audit_reason(ctx: commands.Context, reason: str) -> str:
    moderator = f"{ctx.author} ({ctx.author.id})"
    return f"{reason.strip() or 'No reason provided'} | Moderator: {moderator}"[:512]


def _message_id(ctx: commands.Context) -> int:
    if ctx.interaction is not None:
        return ctx.interaction.id
    return ctx.message.id


def _validate_target(ctx: commands.Context, member: discord.Member) -> None:
    guild = ctx.guild
    author = ctx.author
    if guild is None or not isinstance(author, discord.Member):
        raise commands.NoPrivateMessage
    if member.id == author.id:
        raise commands.BadArgument("You cannot moderate yourself.")
    if member.id == guild.owner_id:
        raise commands.BadArgument("The server owner cannot be moderated.")
    if author.id != guild.owner_id and member.top_role >= author.top_role:
        raise commands.BadArgument(
            "That member's highest role is equal to or above yours."
        )
    bot_member = guild.me
    if bot_member is None or member.top_role >= bot_member.top_role:
        raise commands.BadArgument(
            "My highest role must be above the target member's highest role."
        )


async def _try_dm(member: discord.abc.User, message: str) -> bool:
    try:
        await member.send(message)
    except (discord.Forbidden, discord.HTTPException):
        LOGGER.debug("Could not direct-message moderated user %s", member.id)
        return False
    return True


class Moderation(commands.Cog):
    """Safe, typed moderation and case-history commands."""

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot used for database-backed moderation records."""
        self.bot = bot

    async def _record_case(
        self, ctx: commands.Context, member: discord.abc.User, reason: str
    ) -> None:
        statement = (
            "INSERT INTO warnings (userid, guildid, warning, messageid) "
            "VALUES ($1, $2, $3, $4)"
        )
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                statement,
                member.id,
                ctx.guild.id,
                reason,
                _message_id(ctx),
            )

    @commands.hybrid_command(
        aliases=["lockdown", "restrict", "startlockdown"],
        brief="Prevent a role from sending messages in a channel.",
        description=(
            "Lock a text channel for the default role or a selected role without "
            "replacing its other permission overwrites."
        ),
        usage="[channel] [role] [reason]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel | None = None,
        role: discord.Role | None = None,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Lock one text channel while preserving unrelated overwrites."""
        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel):
            raise commands.BadArgument("Choose a text channel to lock.")
        target_role = role or ctx.guild.default_role
        await target.set_permissions(
            target_role,
            send_messages=False,
            reason=_audit_reason(ctx, reason),
        )
        await ctx.send(
            f"🔒 {target.mention} is locked for {target_role.mention}. Reason: {reason}",
            ephemeral=True,
        )

    @commands.hybrid_command(
        aliases=["stoplockdown", "unrestrict"],
        brief="Restore inherited send permission in a locked channel.",
        description=(
            "Unlock a text channel by returning the selected role's send-messages "
            "permission to its inherited state."
        ),
        usage="[channel] [role] [reason]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlock(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel | None = None,
        role: discord.Role | None = None,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Unlock one text channel without changing other permissions."""
        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel):
            raise commands.BadArgument("Choose a text channel to unlock.")
        target_role = role or ctx.guild.default_role
        await target.set_permissions(
            target_role,
            send_messages=None,
            reason=_audit_reason(ctx, reason),
        )
        await ctx.send(
            f"🔓 {target.mention} is unlocked for {target_role.mention}. Reason: {reason}",
            ephemeral=True,
        )

    @commands.hybrid_command(
        aliases=["slowmode"],
        brief="Set this channel's slowmode delay.",
        description="Set the current text channel's slowmode from 0 to 21,600 seconds.",
        usage="<seconds> [reason]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def setslowmode(
        self,
        ctx: commands.Context,
        seconds: commands.Range[int, 0, 21600] = 0,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Set a Discord-valid slowmode delay."""
        await ctx.channel.edit(
            slowmode_delay=seconds, reason=_audit_reason(ctx, reason)
        )
        await ctx.send(
            f"Slowmode is now {seconds} second(s) in {ctx.channel.mention}.",
            ephemeral=True,
        )

    @commands.hybrid_command(
        brief="Delete a bounded number of recent messages.",
        description=(
            "Delete 1-1000 recent messages, optionally only messages from one member."
        ),
        usage="<amount> [member] [reason]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge(
        self,
        ctx: commands.Context,
        amount: commands.Range[int, 1, 1000],
        member: discord.Member | None = None,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Purge recent messages with explicit bounds and optional filtering."""
        check = None if member is None else lambda message: message.author == member
        deleted = await ctx.channel.purge(
            limit=amount,
            check=check,
            reason=_audit_reason(ctx, reason),
        )
        scope = "" if member is None else f" from {member.mention}"
        await ctx.send(
            f"Deleted {len(deleted)} message(s){scope}. Reason: {reason}",
            delete_after=8,
            ephemeral=True,
        )

    @commands.hybrid_command(
        brief="Delete recent messages sent by this bot.",
        description="Delete 1-1000 recent messages authored by Aestron.",
        usage="<amount> [reason]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def selfpurge(
        self,
        ctx: commands.Context,
        amount: commands.Range[int, 1, 1000],
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Purge only messages authored by this bot."""
        deleted = await ctx.channel.purge(
            limit=amount,
            check=lambda message: message.author.id == self.bot.user.id,
            reason=_audit_reason(ctx, reason),
        )
        await ctx.send(
            f"Deleted {len(deleted)} bot message(s).",
            delete_after=8,
            ephemeral=True,
        )

    @commands.hybrid_command(
        brief="Record a warning for a member.",
        description="Record a warning and notify the member when direct messages allow it.",
        usage="<member> <reason>",
    )
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def warn(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str,
    ) -> None:
        """Record one validated warning."""
        _validate_target(ctx, member)
        case_reason = _audit_reason(ctx, reason)
        await self._record_case(ctx, member, case_reason)
        notified = await _try_dm(
            member, f"You were warned in **{ctx.guild.name}**. Reason: {reason}"
        )
        suffix = "" if notified else " (DM delivery failed)"
        await ctx.send(
            f"⚠️ Warned {member.mention}. Reason: {reason}{suffix}", ephemeral=True
        )

    @commands.hybrid_command(
        aliases=["punishments"],
        brief="Show a member's warning history.",
        description="Show up to the 25 most recent warning and moderation records.",
        usage="<member>",
    )
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def warnings(self, ctx: commands.Context, member: discord.Member) -> None:
        """Display recent warning records without unbounded queries."""
        query = (
            "SELECT warning FROM warnings WHERE userid = $1 AND guildid = $2 "
            "ORDER BY messageid DESC LIMIT 25"
        )
        async with self.bot.database.pool.acquire() as connection:
            rows = await connection.fetch(query, member.id, ctx.guild.id)
        if not rows:
            await ctx.send(f"{member.mention} has no warning records.", ephemeral=True)
            return
        description = "\n".join(
            f"**{index}.** {str(row['warning'])[:350]}"
            for index, row in enumerate(rows, start=1)
        )
        await ctx.send(
            embed=discord.Embed(
                title=f"Warnings for {member}",
                description=description[:4096],
                color=discord.Color.orange(),
            ),
            ephemeral=True,
        )

    @commands.hybrid_command(
        aliases=["clearwarns", "delwarnings"],
        brief="Clear a member's warning history.",
        description="Permanently clear all stored warnings for one member in this guild.",
        usage="<member> [reason]",
    )
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def clearwarnings(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Clear warning history with a parameterized query."""
        query = "DELETE FROM warnings WHERE userid = $1 AND guildid = $2"
        async with self.bot.database.pool.acquire() as connection:
            result = await connection.execute(query, member.id, ctx.guild.id)
        deleted = int(result.rsplit(" ", maxsplit=1)[-1])
        await ctx.send(
            f"Cleared {deleted} warning(s) for {member.mention}. Reason: {reason}",
            ephemeral=True,
        )

    @commands.hybrid_command(
        brief="Ban a member from this server.",
        description="Ban one member and optionally delete up to seven days of messages.",
        usage="<member> [delete_message_seconds] [reason]",
    )
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(
        self,
        ctx: commands.Context,
        member: discord.Member,
        delete_message_seconds: commands.Range[int, 0, 604800] = 0,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Ban a hierarchy-validated member using the current Discord API."""
        _validate_target(ctx, member)
        audit_reason = _audit_reason(ctx, reason)
        notified = await _try_dm(
            member, f"You were banned from **{ctx.guild.name}**. Reason: {reason}"
        )
        await ctx.guild.ban(
            member,
            delete_message_seconds=delete_message_seconds,
            reason=audit_reason,
        )
        await self._record_case(ctx, member, f"Ban: {audit_reason}")
        suffix = "" if notified else " (DM delivery failed)"
        await ctx.send(f"🔨 Banned {member}{suffix}. Reason: {reason}", ephemeral=True)

    @commands.hybrid_command(
        brief="Unban a user by selecting or supplying their account.",
        description="Verify that a user is banned, then remove their guild ban.",
        usage="<user> [reason]",
    )
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(
        self,
        ctx: commands.Context,
        user: discord.User,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Unban one user without fetching the complete ban list."""
        try:
            await ctx.guild.fetch_ban(user)
        except discord.NotFound as error:
            raise commands.BadArgument(f"{user} is not banned.") from error
        audit_reason = _audit_reason(ctx, reason)
        await ctx.guild.unban(user, reason=audit_reason)
        await self._record_case(ctx, user, f"Unban: {audit_reason}")
        await _try_dm(
            user, f"You were unbanned from **{ctx.guild.name}**. Reason: {reason}"
        )
        await ctx.send(f"Unbanned {user}. Reason: {reason}", ephemeral=True)

    @commands.hybrid_command(
        aliases=["bans", "guildbans", "banned", "serverbans"],
        brief="List recent server bans.",
        description="List up to 100 banned users without an unbounded API request.",
        usage="",
    )
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def checkbans(self, ctx: commands.Context) -> None:
        """List bans in embed-sized pages."""
        entries = [entry async for entry in ctx.guild.bans(limit=100)]
        if not entries:
            await ctx.send("This server has no bans.", ephemeral=True)
            return
        for offset in range(0, len(entries), 10):
            embed = discord.Embed(title="Server bans", color=discord.Color.red())
            for entry in entries[offset : offset + 10]:
                embed.add_field(
                    name=f"{entry.user} ({entry.user.id})",
                    value=f"Reason: {entry.reason or 'No reason provided'}"[:1024],
                    inline=False,
                )
            embed.set_footer(
                text=f"Showing {offset + 1}-{min(offset + 10, len(entries))}"
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="Kick a member from this server.",
        description="Kick one hierarchy-validated member and record the action.",
        usage="<member> [reason]",
    )
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Kick a hierarchy-validated guild member."""
        _validate_target(ctx, member)
        audit_reason = _audit_reason(ctx, reason)
        notified = await _try_dm(
            member, f"You were kicked from **{ctx.guild.name}**. Reason: {reason}"
        )
        await member.kick(reason=audit_reason)
        await self._record_case(ctx, member, f"Kick: {audit_reason}")
        suffix = "" if notified else " (DM delivery failed)"
        await ctx.send(f"Kicked {member}{suffix}. Reason: {reason}", ephemeral=True)

    @commands.hybrid_command(
        aliases=["mute"],
        brief="Temporarily timeout a member.",
        description="Timeout a member for 1 second to 28 days using `30m`, `2h`, or `1d`.",
        usage="<member> <duration> [reason]",
    )
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout(
        self,
        ctx: commands.Context,
        member: discord.Member,
        duration: str,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Apply Discord's native timeout instead of legacy mute roles."""
        _validate_target(ctx, member)
        delta = parse_duration(duration)
        audit_reason = _audit_reason(ctx, reason)
        until = discord.utils.utcnow() + delta
        await member.timeout(until, reason=audit_reason)
        await self._record_case(ctx, member, f"Timeout until {until}: {audit_reason}")
        await _try_dm(
            member,
            f"You were timed out in **{ctx.guild.name}** for {duration}. Reason: {reason}",
        )
        await ctx.send(
            f"Timed out {member.mention} until {discord.utils.format_dt(until, 'R')}. "
            f"Reason: {reason}",
            ephemeral=True,
        )

    @commands.hybrid_command(
        aliases=["unmute", "removetimeout"],
        brief="Remove a member's active timeout.",
        description="Remove Discord's native communication timeout from one member.",
        usage="<member> [reason]",
    )
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def untimeout(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Remove a native Discord timeout."""
        _validate_target(ctx, member)
        audit_reason = _audit_reason(ctx, reason)
        await member.timeout(None, reason=audit_reason)
        await self._record_case(ctx, member, f"Timeout removed: {audit_reason}")
        await ctx.send(
            f"Removed the timeout from {member.mention}. Reason: {reason}",
            ephemeral=True,
        )

    @commands.hybrid_command(
        brief="Ban and immediately unban a member to clear recent messages.",
        description="Soft-ban a member and remove up to one day of their recent messages.",
        usage="<member> [reason]",
    )
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def softban(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Perform a hierarchy-validated soft ban."""
        _validate_target(ctx, member)
        audit_reason = _audit_reason(ctx, reason)
        await _try_dm(
            member, f"You were soft-banned from **{ctx.guild.name}**. Reason: {reason}"
        )
        await ctx.guild.ban(member, delete_message_seconds=86400, reason=audit_reason)
        try:
            await ctx.guild.unban(member, reason=f"Soft-ban completion: {audit_reason}")
        except discord.HTTPException:
            LOGGER.exception("Soft-ban unban step failed for user %s", member.id)
            raise
        await self._record_case(ctx, member, f"Soft-ban: {audit_reason}")
        await ctx.send(f"Soft-banned {member}. Reason: {reason}", ephemeral=True)

    @commands.hybrid_command(
        aliases=["nickname"],
        brief="Set or clear a member's server nickname.",
        description="Set a nickname, or omit it to clear the current nickname.",
        usage="<member> [nickname] [reason]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def nick(
        self,
        ctx: commands.Context,
        member: discord.Member,
        nickname: str | None = None,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Set a validated nickname of at most 32 characters."""
        _validate_target(ctx, member)
        if nickname is not None and len(nickname) > 32:
            raise commands.BadArgument("Nicknames cannot exceed 32 characters.")
        await member.edit(nick=nickname, reason=_audit_reason(ctx, reason))
        value = nickname or "their account name"
        await ctx.send(
            f"Updated {member.mention}'s display name to {value}.", ephemeral=True
        )

    @commands.cooldown(1, 30, commands.BucketType.channel)
    @commands.hybrid_command(
        aliases=["snipemsg", "whodeleted", "sn"],
        brief="Show the most recently deleted message in this channel.",
        description="Show the latest stored deleted-message record for this channel.",
        usage="",
    )
    @commands.guild_only()
    async def snipe(self, ctx: commands.Context) -> None:
        """Retrieve a bounded, safely formatted snipe record."""
        query = "SELECT * FROM snipelog WHERE channelid = $1"
        async with self.bot.database.pool.acquire() as connection:
            row = await connection.fetchrow(query, ctx.channel.id)
        if row is None:
            await ctx.send("There are no recently deleted messages.", ephemeral=True)
            return
        content = str(row["content"] or "No text content")
        content = re.sub(r"https?://\S+", "[link hidden]", content)
        content = discord.utils.escape_markdown(content)[:1024]
        embed = discord.Embed(
            title="Recently deleted message",
            timestamp=row["timedeletion"],
            color=discord.Color.orange(),
        )
        embed.add_field(name="Author", value=str(row["username"])[:1024])
        embed.add_field(name="Content", value=content, inline=False)
        raw_embeds = row.get("embeds") if hasattr(row, "get") else None
        if raw_embeds:
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                if json.loads(raw_embeds):
                    embed.set_footer(
                        text="The deleted message also contained an embed."
                    )
        await ctx.send(embed=embed, ephemeral=True)
