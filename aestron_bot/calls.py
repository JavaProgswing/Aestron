"""Private, consent-based Discord DM calls with bounded message relay."""

from __future__ import annotations

import contextlib
import logging

import discord
from discord import app_commands
from discord.ext import commands

LOGGER = logging.getLogger(__name__)
MAX_RELAY_ATTACHMENTS = 3
MAX_RELAY_BYTES = 8 * 1024 * 1024


class CallInviteView(discord.ui.View):
    """Short-lived accept/decline controls visible only in the receiver's DM."""

    def __init__(self, receiver_id: int) -> None:
        """Create a one-minute invitation for exactly one receiver."""
        super().__init__(timeout=60)
        self.receiver_id = receiver_id
        self.accepted: bool | None = None
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Reject answers from anyone except the intended receiver."""
        if interaction.user.id == self.receiver_id:
            return True
        await interaction.response.send_message(
            "Only the call receiver can answer this invitation.", ephemeral=True
        )
        return False

    async def _answer(self, interaction: discord.Interaction, accepted: bool) -> None:
        self.accepted = accepted
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="Call accepted." if accepted else "Call declined.",
            embed=None,
            view=self,
        )
        self.stop()

    @discord.ui.button(label="Accept", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Accept the pending call."""
        await self._answer(interaction, True)

    @discord.ui.button(label="Decline", emoji="✖️", style=discord.ButtonStyle.danger)
    async def decline(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Decline the pending call."""
        await self._answer(interaction, False)

    async def on_timeout(self) -> None:
        """Disable unanswered controls after one minute."""
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            with contextlib.suppress(discord.NotFound, discord.HTTPException):
                await self.message.edit(
                    content="Call invitation expired.", embed=None, view=self
                )


class Calls(commands.Cog):
    """Opt-in private calls that relay only consenting users' direct messages."""

    calls = app_commands.Group(name="calls", description="Manage private DM calls.")

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize active and pending in-memory call state."""
        self.bot = bot
        self._peers: dict[int, int] = {}
        self._pending: set[int] = set()

    async def cog_load(self) -> None:
        """Create the privacy-preference table when the database is available."""
        if not self.bot.database.connected:
            return
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS callsettings ("
                "userid BIGINT PRIMARY KEY, settingbool BOOLEAN NOT NULL DEFAULT FALSE)"
            )

    async def _enabled(self, user_id: int) -> bool:
        async with self.bot.database.pool.acquire() as connection:
            value = await connection.fetchval(
                "SELECT settingbool FROM callsettings WHERE userid = $1", user_id
            )
        return bool(value)

    async def _set_enabled(self, user_id: int, enabled: bool) -> None:
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO callsettings (userid, settingbool) VALUES ($1, $2) "
                "ON CONFLICT (userid) DO UPDATE SET settingbool = EXCLUDED.settingbool",
                user_id,
                enabled,
            )

    def _busy(self, user_id: int) -> bool:
        return user_id in self._peers or user_id in self._pending

    async def _end(self, user_id: int, reason: str) -> bool:
        peer_id = self._peers.pop(user_id, None)
        if peer_id is None:
            return False
        self._peers.pop(peer_id, None)
        for target_id in (user_id, peer_id):
            target = self.bot.get_user(target_id)
            if target is not None:
                with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                    await target.send(f"Call ended: {reason}")
        return True

    @commands.hybrid_command(
        with_app_command=False,
        aliases=["callsettings", "togglecall"],
        brief="Enable or disable incoming DM calls.",
        description="Toggle whether other members may send you private call invitations.",
        usage="[enabled]",
    )
    @commands.cooldown(2, 10, commands.BucketType.user)
    async def calltoggle(
        self, ctx: commands.Context, enabled: bool | None = None
    ) -> None:
        """Toggle incoming call consent through prefix commands."""
        current = await self._enabled(ctx.author.id)
        new_value = not current if enabled is None else enabled
        await self._set_enabled(ctx.author.id, new_value)
        await ctx.send(
            f"Incoming calls are now **{'enabled' if new_value else 'disabled'}**.",
            ephemeral=True,
        )

    @commands.hybrid_command(
        brief="Invite a member to a private DM call.",
        description=(
            "Send a consent prompt in DMs, then relay only direct messages between "
            "both participants until either person hangs up."
        ),
        usage="<member> [reason]",
    )
    @commands.guild_only()
    @commands.cooldown(1, 45, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user, wait=False)
    async def call(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str | None = None,
    ) -> None:
        """Request consent and connect a private DM relay."""
        if member.id == ctx.author.id:
            raise commands.BadArgument("You cannot call yourself.")
        if member.bot:
            raise commands.BadArgument("Bots cannot join relayed calls.")
        if self._busy(ctx.author.id) or self._busy(member.id):
            raise commands.BadArgument("One of you is already in or answering a call.")
        if not await self._enabled(member.id):
            await ctx.send(
                "That member has incoming calls disabled. They can opt in with "
                "`a!calltoggle`.",
                ephemeral=True,
            )
            return
        reason = " ".join((reason or "No reason provided").split())[:300]
        view = CallInviteView(member.id)
        embed = discord.Embed(
            title="Incoming private call",
            description=(
                f"**{ctx.author}** (`{ctx.author.id}`) is calling from "
                f"**{ctx.guild.name}**.\n\n**Reason:** {reason}"
            ),
            color=0x5865F2,
        )
        embed.set_footer(text="Messages are relayed only after you accept")
        self._pending.update((ctx.author.id, member.id))
        try:
            view.message = await member.send(embed=embed, view=view)
        except (discord.Forbidden, discord.HTTPException):
            self._pending.difference_update((ctx.author.id, member.id))
            await ctx.send(
                "I could not DM that member. They need to allow server-member DMs.",
                ephemeral=True,
            )
            return
        await ctx.send(
            f"Call invitation sent privately to {member.mention}.", ephemeral=True
        )
        await view.wait()
        self._pending.difference_update((ctx.author.id, member.id))
        if view.accepted is not True:
            with contextlib.suppress(discord.Forbidden, discord.HTTPException):
                await ctx.author.send(f"{member} declined or did not answer your call.")
            return
        if self._busy(ctx.author.id) or self._busy(member.id):
            await ctx.author.send(
                "The call could not start because a participant is busy."
            )
            await member.send("The call could not start because a participant is busy.")
            return
        self._peers[ctx.author.id] = member.id
        self._peers[member.id] = ctx.author.id
        instructions = (
            "Call connected. Send messages here in this DM with Aestron. "
            "Use `a!hangup` or `/calls hangup` to end it."
        )
        await ctx.author.send(f"{instructions}\nConnected to **{member}**.")
        await member.send(f"{instructions}\nConnected to **{ctx.author}**.")

    @commands.hybrid_command(
        with_app_command=False,
        brief="End your active private call.",
        description="Immediately stop relaying messages for both call participants.",
        usage="",
    )
    async def hangup(self, ctx: commands.Context) -> None:
        """End a call through prefix commands."""
        ended = await self._end(ctx.author.id, f"{ctx.author} hung up")
        if not ended:
            await ctx.send("You are not in an active call.", ephemeral=True)

    @calls.command(name="privacy", description="Set incoming-call privacy.")
    async def slash_privacy(
        self, interaction: discord.Interaction, enabled: bool
    ) -> None:
        """Set incoming call consent through slash commands."""
        await self._set_enabled(interaction.user.id, enabled)
        await interaction.response.send_message(
            f"Incoming calls are now **{'enabled' if enabled else 'disabled'}**.",
            ephemeral=True,
        )

    @calls.command(name="status", description="Show private-call status.")
    async def slash_status(self, interaction: discord.Interaction) -> None:
        """Show call privacy and activity privately."""
        privacy = await self._enabled(interaction.user.id)
        active = interaction.user.id in self._peers
        await interaction.response.send_message(
            f"Incoming calls: **{'enabled' if privacy else 'disabled'}**\n"
            f"Active call: **{'yes' if active else 'no'}**",
            ephemeral=True,
        )

    @calls.command(name="hangup", description="End your active private call.")
    async def slash_hangup(self, interaction: discord.Interaction) -> None:
        """End a call through slash commands."""
        ended = await self._end(interaction.user.id, f"{interaction.user} hung up")
        await interaction.response.send_message(
            "Call ended." if ended else "You are not in an active call.",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Relay bounded content only from a participant's direct-message channel."""
        if message.author.bot or message.guild is not None:
            return
        peer_id = self._peers.get(message.author.id)
        if peer_id is None:
            return
        context = await self.bot.get_context(message)
        if context.valid:
            return
        peer = self.bot.get_user(peer_id)
        if peer is None:
            await self._end(message.author.id, "the other participant is unavailable")
            return
        embed = discord.Embed(
            description=(message.content[:4000] or "*Attachment message*"),
            color=0x5865F2,
            timestamp=message.created_at,
        )
        embed.set_author(
            name=f"{message.author} · private call",
            icon_url=message.author.display_avatar.url,
        )
        files = []
        total_size = 0
        for attachment in message.attachments[:MAX_RELAY_ATTACHMENTS]:
            if total_size + attachment.size > MAX_RELAY_BYTES:
                break
            try:
                files.append(await attachment.to_file(use_cached=True))
                total_size += attachment.size
            except (discord.HTTPException, OSError):
                LOGGER.warning("Could not copy call attachment", exc_info=True)
        try:
            await peer.send(
                embed=embed,
                files=files,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            await self._end(message.author.id, "messages could no longer be delivered")
