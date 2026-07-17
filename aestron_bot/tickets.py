"""Persistent, permission-safe support ticket panels."""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC

import discord
from discord import app_commands
from discord.ext import commands

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TicketSetupResult:
    """Resources created or reused by guided ticket setup."""

    panel: discord.Message
    support_role: discord.Role
    category: discord.CategoryChannel
    log_channel: discord.TextChannel


def _safe_channel_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]", "-", name.casefold()).strip("-")
    cleaned = re.sub(r"-+", "-", cleaned)
    return cleaned[:70] or "member"


class OpenTicketView(discord.ui.View):
    """Persistent panel button used by every configured ticket panel."""

    def __init__(self) -> None:
        """Create a persistent view with a stable custom identifier."""
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Open ticket",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="aestron:ticket:open:v1",
    )
    async def open_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Open or locate the user's ticket for this panel."""
        cog = interaction.client.get_cog("Tickets")
        if cog is None:
            await interaction.response.send_message(
                "Ticket service is unavailable.", ephemeral=True
            )
            return
        await cog.open_ticket(interaction)


class TicketControls(discord.ui.View):
    """Persistent staff and owner controls for ticket channels."""

    def __init__(self) -> None:
        """Create stable ticket controls."""
        super().__init__(timeout=None)

    async def _cog(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Tickets")
        if cog is None:
            await interaction.response.send_message(
                "Ticket service is unavailable.", ephemeral=True
            )
        return cog

    @discord.ui.button(
        label="Claim",
        emoji="🙋",
        style=discord.ButtonStyle.secondary,
        custom_id="aestron:ticket:claim:v1",
    )
    async def claim(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Claim the current ticket as support staff."""
        if cog := await self._cog(interaction):
            await cog.claim_ticket(interaction)

    @discord.ui.button(
        label="Lock / unlock",
        emoji="🔒",
        style=discord.ButtonStyle.secondary,
        custom_id="aestron:ticket:lock:v1",
    )
    async def lock(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Toggle whether the ticket owner can send messages."""
        if cog := await self._cog(interaction):
            await cog.toggle_lock(interaction)

    @discord.ui.button(
        label="Transcript",
        emoji="📄",
        style=discord.ButtonStyle.secondary,
        custom_id="aestron:ticket:transcript:v1",
    )
    async def transcript(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Export a bounded plain-text transcript."""
        if cog := await self._cog(interaction):
            await cog.send_transcript(interaction)

    @discord.ui.button(
        label="Close",
        emoji="✅",
        style=discord.ButtonStyle.danger,
        custom_id="aestron:ticket:close:v1",
    )
    async def close(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Archive the current ticket without destroying its history."""
        if cog := await self._cog(interaction):
            await cog.close_ticket(interaction)


class Tickets(commands.Cog):
    """Database-backed ticket panels with persistent button controls."""

    ticket = app_commands.Group(name="ticket", description="Manage support tickets.")

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize per-guild creation locks."""
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}
        self._open_attempts: dict[tuple[int, int], float] = {}

    async def cog_load(self) -> None:
        """Create ticket tables and register persistent controls."""
        self.bot.add_view(OpenTicketView())
        self.bot.add_view(TicketControls())
        if not self.bot.database.connected:
            return
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS ticketchannels ("
                "channelid BIGINT NOT NULL, categoryid BIGINT, roleid BIGINT NOT NULL, "
                "messageid BIGINT PRIMARY KEY, emoji TEXT NOT NULL)"
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_panels (
                    message_id BIGINT PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    channel_id BIGINT NOT NULL,
                    support_role_id BIGINT NOT NULL,
                    category_id BIGINT,
                    log_channel_id BIGINT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS support_tickets (
                    channel_id BIGINT PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    owner_id BIGINT NOT NULL,
                    panel_message_id BIGINT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    claimed_by BIGINT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    closed_at TIMESTAMPTZ,
                    CHECK (status IN ('open', 'locked', 'closed'))
                )
                """
            )
            await connection.execute(
                "CREATE INDEX IF NOT EXISTS support_tickets_owner_status_idx "
                "ON support_tickets (guild_id, owner_id, status)"
            )

    async def _panel(self, message_id: int):
        async with self.bot.database.pool.acquire() as connection:
            return await connection.fetchrow(
                "SELECT * FROM ticket_panels WHERE message_id = $1", message_id
            )

    async def _ticket(self, channel_id: int):
        async with self.bot.database.pool.acquire() as connection:
            return await connection.fetchrow(
                "SELECT * FROM support_tickets WHERE channel_id = $1", channel_id
            )

    async def _is_staff(self, member: discord.Member, ticket) -> bool:
        if member.guild_permissions.manage_channels:
            return True
        panel = await self._panel(int(ticket["panel_message_id"]))
        return bool(
            panel and any(role.id == panel["support_role_id"] for role in member.roles)
        )

    async def _log_event(
        self,
        guild: discord.Guild,
        *,
        kind: str,
        title: str,
        target: discord.abc.Snowflake | str,
        actor: discord.abc.User,
        reason: str,
    ) -> None:
        """Publish one normalized ticket event without blocking ticket work."""
        audit_logging = self.bot.get_cog("AuditLogging")
        if audit_logging is None:
            return
        target_id = getattr(target, "id", None)
        try:
            await audit_logging.dispatch(
                guild,
                kind=f"ticket_{kind}",
                title=title,
                target=(
                    f"{target} (`{target_id}`)"
                    if target_id is not None
                    else str(target)
                ),
                target_id=target_id,
                actor_override=actor,
                reason_override=reason,
                color=discord.Color.blurple(),
            )
        except Exception:
            LOGGER.exception("Could not publish ticket event guild=%s", guild.id)

    async def _require_ticket_access(
        self,
        interaction: discord.Interaction,
        *,
        staff_only: bool = False,
        allow_closed: bool = False,
    ):
        ticket = await self._ticket(interaction.channel_id)
        if ticket is None:
            await interaction.response.send_message(
                "This channel is not an active Aestron ticket.", ephemeral=True
            )
            return None
        if ticket["status"] == "closed" and not allow_closed:
            await interaction.response.send_message(
                "This ticket is already closed. Its transcript is still available.",
                ephemeral=True,
            )
            return None
        member = interaction.user
        is_staff = isinstance(member, discord.Member) and await self._is_staff(
            member, ticket
        )
        is_owner = member.id == ticket["owner_id"]
        if (staff_only and not is_staff) or (
            not staff_only and not (is_staff or is_owner)
        ):
            await interaction.response.send_message(
                "You do not have permission to manage this ticket.", ephemeral=True
            )
            return None
        return ticket

    async def setup_panel(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel | discord.ForumChannel,
        support_role: discord.Role | None,
        category: discord.CategoryChannel | None,
        log_channel: discord.TextChannel | None,
        message: str,
    ) -> TicketSetupResult:
        """Create missing defaults and persist one ticket panel."""
        if channel.guild.id != guild.id:
            raise commands.BadArgument("The panel channel must be in this server.")
        if support_role is not None and support_role.guild.id != guild.id:
            raise commands.BadArgument("The support role must be in this server.")
        if category is not None and category.guild.id != guild.id:
            raise commands.BadArgument("The category must be in this server.")
        if log_channel is not None and log_channel.guild.id != guild.id:
            raise commands.BadArgument("The log channel must be in this server.")
        bot_member = guild.me
        if bot_member is None:
            raise commands.BotMissingPermissions(["manage_channels", "manage_roles"])
        if support_role is None:
            support_role = discord.utils.get(guild.roles, name="Support Team")
        if support_role is None:
            if not bot_member.guild_permissions.manage_roles:
                raise commands.BotMissingPermissions(["manage_roles"])
            support_role = await guild.create_role(
                name="Support Team",
                reason="Aestron guided ticket setup",
            )
        if support_role.managed:
            raise commands.BadArgument(
                "Choose a normal server role; integration-managed roles cannot manage tickets."
            )
        if support_role >= bot_member.top_role:
            raise commands.BadArgument(
                "Move my highest role above the support role, then run setup again."
            )
        if category is None:
            category = discord.utils.get(guild.categories, name="Support Tickets")
        if category is None:
            category = await guild.create_category(
                "Support Tickets", reason="Aestron guided ticket setup"
            )
        if log_channel is None:
            log_channel = discord.utils.get(category.text_channels, name="ticket-logs")
        if log_channel is None:
            log_channel = await guild.create_text_channel(
                "ticket-logs",
                category=category,
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    support_role: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                    ),
                    bot_member: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                    ),
                },
                reason="Aestron guided ticket setup",
            )
        else:
            await log_channel.set_permissions(
                guild.default_role,
                view_channel=False,
                reason="Aestron private ticket logs",
            )
            await log_channel.set_permissions(
                support_role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                reason="Aestron support log access",
            )
            await log_channel.set_permissions(
                bot_member,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                reason="Aestron ticket log access",
            )
        channel_permissions = channel.permissions_for(bot_member)
        missing = [
            permission
            for permission in ("view_channel", "send_messages", "embed_links")
            if not getattr(channel_permissions, permission, False)
        ]
        if not bot_member.guild_permissions.manage_channels:
            missing.append("manage_channels")
        if missing:
            raise commands.BotMissingPermissions(missing)
        embed = discord.Embed(
            title="Support tickets",
            description=message[:4000],
            color=0x5865F2,
        )
        embed.add_field(
            name="Before opening",
            value="Describe the issue clearly and avoid sharing passwords or tokens.",
            inline=False,
        )
        embed.set_footer(text="One open ticket per member")
        if isinstance(channel, discord.ForumChannel):
            created = await channel.create_thread(
                name="Open a support ticket",
                embed=embed,
                view=OpenTicketView(),
                reason="Aestron ticket panel setup",
            )
            panel_message = created.message
        else:
            panel_message = await channel.send(embed=embed, view=OpenTicketView())
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO ticket_panels "
                "(message_id, guild_id, channel_id, support_role_id, category_id, log_channel_id) "
                "VALUES ($1, $2, $3, $4, $5, $6) "
                "ON CONFLICT (message_id) DO UPDATE SET "
                "support_role_id = EXCLUDED.support_role_id, "
                "category_id = EXCLUDED.category_id, log_channel_id = EXCLUDED.log_channel_id",
                panel_message.id,
                guild.id,
                panel_message.channel.id,
                support_role.id,
                category.id,
                log_channel.id,
            )
        return TicketSetupResult(
            panel=panel_message,
            support_role=support_role,
            category=category,
            log_channel=log_channel,
        )

    async def _open_for_member(
        self,
        guild: discord.Guild,
        owner: discord.Member,
        panel_message_id: int,
    ) -> tuple[discord.TextChannel | None, bool, str | None]:
        """Open or locate one member's ticket under a per-guild creation lock."""
        panel = await self._panel(panel_message_id)
        if panel is None:
            return None, False, "This ticket panel is no longer configured."
        async with self._locks.setdefault(guild.id, asyncio.Lock()):
            async with self.bot.database.pool.acquire() as connection:
                existing = await connection.fetchrow(
                    "SELECT channel_id FROM support_tickets "
                    "WHERE guild_id = $1 AND owner_id = $2 AND status IN ('open', 'locked') "
                    "ORDER BY created_at DESC LIMIT 1",
                    guild.id,
                    owner.id,
                )
            if existing:
                channel = guild.get_channel(int(existing["channel_id"]))
                if isinstance(channel, discord.TextChannel):
                    return channel, False, None
                async with self.bot.database.pool.acquire() as connection:
                    await connection.execute(
                        "UPDATE support_tickets SET status = 'closed', closed_at = NOW() "
                        "WHERE channel_id = $1",
                        int(existing["channel_id"]),
                    )
            support_role = guild.get_role(int(panel["support_role_id"]))
            category = (
                guild.get_channel(int(panel["category_id"]))
                if panel["category_id"]
                else None
            )
            if support_role is None:
                return (
                    None,
                    False,
                    "The configured support role was deleted. Ask an administrator "
                    "to rerun ticket setup.",
                )
            if guild.me is None:
                return None, False, "The bot member is unavailable in this server."
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                owner: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                ),
                support_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                ),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_channels=True,
                ),
            }
            try:
                channel = await guild.create_text_channel(
                    f"ticket-{_safe_channel_name(owner.name)}",
                    category=category
                    if isinstance(category, discord.CategoryChannel)
                    else None,
                    overwrites=overwrites,
                    reason=f"Ticket opened by {owner} ({owner.id})",
                )
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.exception("Ticket channel creation failed guild=%s", guild.id)
                return (
                    None,
                    False,
                    "I could not create the ticket channel. Check Manage Channels and "
                    "the bot's role hierarchy.",
                )
            async with self.bot.database.pool.acquire() as connection:
                await connection.execute(
                    "INSERT INTO support_tickets "
                    "(channel_id, guild_id, owner_id, panel_message_id) "
                    "VALUES ($1, $2, $3, $4)",
                    channel.id,
                    guild.id,
                    owner.id,
                    panel_message_id,
                )
            embed = discord.Embed(
                title=f"Ticket for {owner.display_name}",
                description=(
                    "Explain what you need help with. Support staff can claim, lock, "
                    "export, or close this ticket using the controls below."
                ),
                color=0x57F287,
            )
            embed.set_footer(text=f"Owner ID: {owner.id}")
            await channel.send(
                content=f"{owner.mention} {support_role.mention}",
                embed=embed,
                view=TicketControls(),
                allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            )
            await self._log_event(
                guild,
                kind="open",
                title="Ticket opened",
                target=channel,
                actor=owner,
                reason=f"Panel message {panel_message_id}",
            )
            return channel, True, None

    async def open_ticket(self, interaction: discord.Interaction) -> None:
        """Create exactly one open ticket per member and guild."""
        if (
            interaction.guild is None
            or interaction.message is None
            or not isinstance(interaction.user, discord.Member)
        ):
            await interaction.response.send_message(
                "Tickets can only be opened from a server panel.", ephemeral=True
            )
            return
        attempt_key = (interaction.guild.id, interaction.user.id)
        now = time.monotonic()
        retry_after = self._open_attempts.get(attempt_key, 0) + 5 - now
        if retry_after > 0:
            await interaction.response.send_message(
                f"Please wait {retry_after:.1f}s before checking your ticket again.",
                ephemeral=True,
            )
            return
        self._open_attempts[attempt_key] = now
        if len(self._open_attempts) > 10_000:
            self._open_attempts = {
                key: attempted
                for key, attempted in self._open_attempts.items()
                if attempted > now - 5
            }
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel, created, error = await self._open_for_member(
            interaction.guild, interaction.user, interaction.message.id
        )
        if error:
            await interaction.followup.send(error, ephemeral=True)
        elif channel is not None:
            prefix = "Your ticket is ready" if created else "You already have a ticket"
            await interaction.followup.send(
                f"{prefix}: {channel.mention}", ephemeral=True
            )

    async def claim_ticket(self, interaction: discord.Interaction) -> None:
        """Assign an active ticket to one staff member."""
        ticket = await self._require_ticket_access(interaction, staff_only=True)
        if ticket is None:
            return
        claimed_by = ticket["claimed_by"]
        if claimed_by is not None:
            message = (
                "You already claimed this ticket."
                if int(claimed_by) == interaction.user.id
                else f"This ticket is already claimed by <@{claimed_by}>."
            )
            await interaction.response.send_message(message, ephemeral=True)
            return
        async with self.bot.database.pool.acquire() as connection:
            claimed_by = await connection.fetchval(
                "UPDATE support_tickets SET claimed_by = $1 "
                "WHERE channel_id = $2 AND claimed_by IS NULL "
                "RETURNING claimed_by",
                interaction.user.id,
                interaction.channel_id,
            )
            if claimed_by is None:
                claimed_by = await connection.fetchval(
                    "SELECT claimed_by FROM support_tickets WHERE channel_id = $1",
                    interaction.channel_id,
                )
        if claimed_by != interaction.user.id:
            message = (
                f"This ticket was just claimed by <@{claimed_by}>."
                if claimed_by is not None
                else "This ticket is no longer available to claim."
            )
            await interaction.response.send_message(message, ephemeral=True)
            return
        await self._log_event(
            interaction.guild,
            kind="claim",
            title="Ticket claimed",
            target=interaction.channel,
            actor=interaction.user,
            reason="Support staff claimed the ticket",
        )
        await interaction.response.send_message(
            f"Ticket claimed by {interaction.user.mention}."
        )

    async def toggle_lock(self, interaction: discord.Interaction) -> None:
        """Toggle the ticket owner's send permission."""
        ticket = await self._require_ticket_access(interaction, staff_only=True)
        if ticket is None:
            return
        owner = interaction.guild.get_member(int(ticket["owner_id"]))
        channel = interaction.channel
        if owner is None or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "The ticket owner or channel is unavailable.", ephemeral=True
            )
            return
        locked = ticket["status"] != "locked"
        await channel.set_permissions(
            owner,
            send_messages=not locked,
            view_channel=True,
            read_message_history=True,
            reason=f"Ticket {'locked' if locked else 'unlocked'} by {interaction.user}",
        )
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "UPDATE support_tickets SET status = $1 WHERE channel_id = $2",
                "locked" if locked else "open",
                channel.id,
            )
        await self._log_event(
            interaction.guild,
            kind="lock" if locked else "unlock",
            title=f"Ticket {'locked' if locked else 'unlocked'}",
            target=channel,
            actor=interaction.user,
            reason="Ticket owner send permission changed",
        )
        await interaction.response.send_message(
            f"Ticket {'locked' if locked else 'unlocked'} by {interaction.user.mention}."
        )

    async def _transcript_file(self, channel: discord.TextChannel) -> discord.File:
        lines = [f"Aestron ticket transcript for #{channel.name} ({channel.id})\n"]
        async for message in channel.history(limit=1000, oldest_first=True):
            timestamp = message.created_at.astimezone(UTC).isoformat()
            content = message.clean_content or "[no text]"
            attachments = " ".join(attachment.url for attachment in message.attachments)
            lines.append(
                f"[{timestamp}] {message.author} ({message.author.id}): {content}"
            )
            if attachments:
                lines.append(f"  Attachments: {attachments}")
        payload = "\n".join(lines).encode("utf-8", errors="replace")
        return discord.File(io.BytesIO(payload), filename=f"ticket-{channel.id}.txt")

    async def send_transcript(self, interaction: discord.Interaction) -> None:
        """Send a private transcript to ticket staff or owner."""
        ticket = await self._require_ticket_access(interaction, allow_closed=True)
        if ticket is None or not isinstance(interaction.channel, discord.TextChannel):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        transcript = await self._transcript_file(interaction.channel)
        await interaction.followup.send(file=transcript, ephemeral=True)

    async def close_ticket(self, interaction: discord.Interaction) -> None:
        """Archive a ticket and preserve its transcript in the panel log channel."""
        ticket = await self._require_ticket_access(interaction)
        if ticket is None or not isinstance(interaction.channel, discord.TextChannel):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel = interaction.channel
        owner = interaction.guild.get_member(int(ticket["owner_id"]))
        panel = await self._panel(int(ticket["panel_message_id"]))
        transcript = await self._transcript_file(channel)
        log_channel = (
            interaction.guild.get_channel(int(panel["log_channel_id"]))
            if panel
            else None
        )
        if isinstance(log_channel, discord.TextChannel):
            embed = discord.Embed(
                title="Ticket closed",
                description=f"{channel.mention} closed by {interaction.user.mention}",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="Owner", value=f"<@{ticket['owner_id']}>")
            embed.add_field(
                name="Claimed by",
                value=f"<@{ticket['claimed_by']}>"
                if ticket["claimed_by"]
                else "Nobody",
            )
            await log_channel.send(embed=embed, file=transcript)
        if owner is not None:
            await channel.set_permissions(
                owner,
                view_channel=True,
                send_messages=False,
                read_message_history=True,
                reason=f"Ticket closed by {interaction.user}",
            )
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "UPDATE support_tickets SET status = 'closed', closed_at = NOW() "
                "WHERE channel_id = $1",
                channel.id,
            )
        await self._log_event(
            interaction.guild,
            kind="close",
            title="Ticket closed",
            target=channel,
            actor=interaction.user,
            reason="Ticket archived and transcript saved",
        )
        if not channel.name.startswith("closed-"):
            await channel.edit(
                name=f"closed-{channel.name}"[:100],
                reason=f"Ticket closed by {interaction.user}",
            )
        await interaction.followup.send(
            "Ticket closed and archived. A transcript was saved to the panel log channel.",
            ephemeral=True,
        )

    async def _modify_member(
        self, interaction: discord.Interaction, member: discord.Member, *, add: bool
    ) -> None:
        ticket = await self._require_ticket_access(interaction, staff_only=True)
        if ticket is None or not isinstance(interaction.channel, discord.TextChannel):
            return
        await interaction.channel.set_permissions(
            member,
            view_channel=True if add else None,
            send_messages=True if add else None,
            read_message_history=True if add else None,
            reason=f"Ticket access {'added' if add else 'removed'} by {interaction.user}",
        )
        await self._log_event(
            interaction.guild,
            kind="member_add" if add else "member_remove",
            title=f"Ticket member {'added' if add else 'removed'}",
            target=member,
            actor=interaction.user,
            reason=f"Ticket channel {interaction.channel_id}",
        )
        await interaction.response.send_message(
            f"{member.mention} was {'added to' if add else 'removed from'} this ticket."
        )

    @commands.hybrid_command(
        with_app_command=False,
        aliases=["createticket", "supportticket", "supportpanel"],
        brief="Create a persistent support ticket panel.",
        description="Create a button-based ticket panel with a support role and category.",
        usage="<channel> <support_role> [category] [message]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_channels=True)
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def createticketpanel(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        support_role: discord.Role,
        category: discord.CategoryChannel | None = None,
        *,
        message: str = "Click below to open a private support ticket.",
    ) -> None:
        """Create a ticket panel through a prefix command."""
        result = await self.setup_panel(
            ctx.guild, channel, support_role, category, None, message
        )
        await ctx.send(
            f"Ticket panel created: {result.panel.jump_url} · Staff: "
            f"{result.support_role.mention} · Rooms: **{result.category.name}** · "
            f"Logs: {result.log_channel.mention}",
            ephemeral=True,
        )

    @ticket.command(name="setup", description="Create a persistent ticket panel.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 30, key=lambda interaction: interaction.guild_id)
    async def slash_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | discord.ForumChannel | None = None,
        support_role: discord.Role | None = None,
        category: discord.CategoryChannel | None = None,
        log_channel: discord.TextChannel | None = None,
        message: str = "Click below to open a private support ticket.",
    ) -> None:
        """Create or reuse the role, category, logs, and ticket panel."""
        panel_channel = channel or interaction.channel
        if interaction.guild is None or not isinstance(
            panel_channel, (discord.TextChannel, discord.ForumChannel)
        ):
            await interaction.response.send_message(
                "Choose a text, announcement, forum, or media channel for the panel.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self.setup_panel(
            interaction.guild,
            panel_channel,
            support_role,
            category,
            log_channel,
            message,
        )
        await interaction.followup.send(
            f"Ticket panel created: {result.panel.jump_url}\n"
            f"Staff: {result.support_role.mention} · "
            f"Rooms: **{result.category.name}** · "
            f"Logs: {result.log_channel.mention}",
            ephemeral=True,
        )

    @ticket.command(name="claim", description="Claim the current support ticket.")
    @app_commands.checks.cooldown(2, 5, key=lambda interaction: interaction.user.id)
    async def slash_claim(self, interaction: discord.Interaction) -> None:
        """Claim a ticket through slash commands."""
        await self.claim_ticket(interaction)

    @ticket.command(name="lock", description="Lock or unlock the current ticket.")
    @app_commands.checks.cooldown(2, 5, key=lambda interaction: interaction.user.id)
    async def slash_lock(self, interaction: discord.Interaction) -> None:
        """Toggle a ticket lock through slash commands."""
        await self.toggle_lock(interaction)

    @ticket.command(name="transcript", description="Export this ticket's transcript.")
    @app_commands.checks.cooldown(1, 15, key=lambda interaction: interaction.user.id)
    async def slash_transcript(self, interaction: discord.Interaction) -> None:
        """Export a ticket through slash commands."""
        await self.send_transcript(interaction)

    @ticket.command(name="close", description="Archive the current ticket safely.")
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.user.id)
    async def slash_close(self, interaction: discord.Interaction) -> None:
        """Close a ticket through slash commands."""
        await self.close_ticket(interaction)

    @ticket.command(name="add", description="Add a member to this ticket.")
    @app_commands.checks.cooldown(2, 5, key=lambda interaction: interaction.user.id)
    async def slash_add(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        """Add ticket access through slash commands."""
        await self._modify_member(interaction, member, add=True)

    @ticket.command(name="remove", description="Remove a member from this ticket.")
    @app_commands.checks.cooldown(2, 5, key=lambda interaction: interaction.user.id)
    async def slash_remove(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        """Remove ticket access through slash commands."""
        await self._modify_member(interaction, member, add=False)

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        """Keep legacy reaction panels functional during migration."""
        if payload.guild_id is None or payload.member is None or payload.member.bot:
            return
        async with self.bot.database.pool.acquire() as connection:
            legacy = await connection.fetchrow(
                "SELECT * FROM ticketchannels WHERE messageid = $1", payload.message_id
            )
        if legacy is None or str(payload.emoji) != str(legacy["emoji"]):
            return
        guild = self.bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id) if guild else None
        if guild is None or not isinstance(channel, discord.TextChannel):
            return
        panel = await self._panel(payload.message_id)
        if panel is None:
            async with self.bot.database.pool.acquire() as connection:
                await connection.execute(
                    "INSERT INTO ticket_panels "
                    "(message_id, guild_id, channel_id, support_role_id, category_id, log_channel_id) "
                    "VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING",
                    payload.message_id,
                    guild.id,
                    channel.id,
                    legacy["roleid"],
                    getattr(channel.category, "id", None),
                    channel.id,
                )
            panel = await self._panel(payload.message_id)
        with contextlib.suppress(discord.HTTPException):
            await channel.get_partial_message(payload.message_id).remove_reaction(
                payload.emoji, payload.member
            )
        if panel is None:
            return
        ticket_channel, created, error = await self._open_for_member(
            guild, payload.member, payload.message_id
        )
        if error:
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await payload.member.send(f"I could not open your ticket: {error}")
            return
        if ticket_channel is not None:
            message = (
                f"Your ticket is ready: {ticket_channel.mention}"
                if created
                else f"You already have a ticket: {ticket_channel.mention}"
            )
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await payload.member.send(message)
