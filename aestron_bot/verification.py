"""Persistent, DM-private CAPTCHA verification."""

from __future__ import annotations

import asyncio
import io
import logging
import secrets
import string
from dataclasses import dataclass

import discord
from captcha.image import ImageCaptcha
from discord import app_commands
from discord.ext import commands

LOGGER = logging.getLogger(__name__)
_CAPTCHA_ALPHABET = string.ascii_uppercase + string.digits


@dataclass(frozen=True, slots=True)
class VerificationConfig:
    """Resolved verification configuration for one guild."""

    guild_id: int
    channel_id: int
    role_id: int
    message_id: int | None
    enabled: bool = True


class VerificationView(discord.ui.View):
    """Restart-safe verification button, including legacy panel compatibility."""

    def __init__(self) -> None:
        """Create a persistent view with the existing stable custom ID."""
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verify",
        emoji="🔐",
        style=discord.ButtonStyle.success,
        custom_id="verification:green",
    )
    async def verify(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Start a private DM challenge and acknowledge the click ephemerally."""
        cog = interaction.client.get_cog("Captcha")
        if cog is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Verification is unavailable right now.", ephemeral=True
            )
            return
        message = await cog.begin_verification(interaction.user)
        await interaction.response.send_message(message, ephemeral=True)


class Captcha(commands.Cog):
    """Configure persistent CAPTCHA verification and verified-channel access."""

    verification = app_commands.Group(
        name="verification", description="Configure CAPTCHA verification."
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Track active users so parallel DM challenges cannot conflict."""
        self.bot = bot
        self._active_users: set[int] = set()
        self._tasks: set[asyncio.Task] = set()

    async def cog_load(self) -> None:
        """Register the persistent button and create configuration storage."""
        self.bot.add_view(VerificationView())
        if not self.bot.database.connected:
            return
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS verifychannels ("
                "channelid BIGINT NOT NULL, guildid BIGINT NOT NULL)"
            )
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS verifymsg ("
                "guildid BIGINT NOT NULL, channelid BIGINT NOT NULL, "
                "messageid BIGINT NOT NULL)"
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS verification_settings (
                    guild_id BIGINT PRIMARY KEY,
                    channel_id BIGINT NOT NULL,
                    role_id BIGINT NOT NULL,
                    message_id BIGINT,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

    async def cog_unload(self) -> None:
        """Cancel outstanding DM listeners during shutdown."""
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def _track(self, coroutine, *, name: str) -> None:
        creator = getattr(self.bot, "create_background_task", None)
        task = (
            creator(coroutine, name=name) if creator else asyncio.create_task(coroutine)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _config(self, guild: discord.Guild) -> VerificationConfig | None:
        async with self.bot.database.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM verification_settings WHERE guild_id = $1", guild.id
            )
            if row:
                return VerificationConfig(
                    guild_id=guild.id,
                    channel_id=int(row["channel_id"]),
                    role_id=int(row["role_id"]),
                    message_id=int(row["message_id"]) if row["message_id"] else None,
                    enabled=bool(row["enabled"]),
                )
            legacy_channel = await connection.fetchval(
                "SELECT channelid FROM verifychannels WHERE guildid = $1 LIMIT 1",
                guild.id,
            )
            legacy_message = await connection.fetchrow(
                "SELECT channelid, messageid FROM verifymsg WHERE guildid = $1 LIMIT 1",
                guild.id,
            )
        role = discord.utils.get(guild.roles, name="Verified")
        channel_id = legacy_channel or (
            legacy_message["channelid"] if legacy_message else None
        )
        if role is None or channel_id is None:
            return None
        return VerificationConfig(
            guild_id=guild.id,
            channel_id=int(channel_id),
            role_id=role.id,
            message_id=int(legacy_message["messageid"]) if legacy_message else None,
        )

    async def begin_verification(self, member: discord.Member) -> str:
        """Send a CAPTCHA privately and continue validation in a tracked task."""
        config = await self._config(member.guild)
        if config is None or not config.enabled:
            return "Verification is not configured in this server."
        role = member.guild.get_role(config.role_id)
        if role is None:
            return "The configured verified role was deleted. Ask an administrator to repair setup."
        if role in member.roles:
            return "You are already verified."
        if member.id in self._active_users:
            return "A verification challenge is already waiting in your DMs."
        bot_member = member.guild.me
        if (
            bot_member is None
            or not bot_member.guild_permissions.manage_roles
            or role >= bot_member.top_role
        ):
            return "I cannot grant the verified role. An administrator must fix my role hierarchy."

        code = "".join(secrets.choice(_CAPTCHA_ALPHABET) for _ in range(5))
        image = await asyncio.to_thread(
            ImageCaptcha(width=280, height=90).generate, code
        )
        embed = discord.Embed(
            title=f"{member.guild.name} verification",
            description=(
                "Reply in this DM with the five-character code. It is case-sensitive "
                "and expires in three minutes. You have three attempts."
            ),
            color=0x57F287,
        )
        embed.set_image(url="attachment://captcha.png")
        try:
            await member.send(
                embed=embed,
                file=discord.File(io.BytesIO(image.read()), filename="captcha.png"),
            )
        except (discord.Forbidden, discord.HTTPException):
            return "I could not DM you. Enable direct messages for this server and try again."

        self._active_users.add(member.id)
        self._track(
            self._await_answer(member, role, code),
            name=f"verification-{member.guild.id}-{member.id}",
        )
        return "Check your DMs for a private CAPTCHA. It expires in three minutes."

    async def _await_answer(
        self, member: discord.Member, role: discord.Role, code: str
    ) -> None:
        """Validate up to three private replies and grant the configured role."""
        try:
            for attempt in range(1, 4):
                try:
                    message = await self.bot.wait_for(
                        "message",
                        timeout=60,
                        check=lambda item: (
                            item.author.id == member.id and item.guild is None
                        ),
                    )
                except TimeoutError:
                    await member.send(
                        "Verification expired. Click Verify to try again."
                    )
                    return
                if secrets.compare_digest(message.content.strip(), code):
                    try:
                        await member.add_roles(
                            role, reason="Aestron CAPTCHA verification completed"
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        await member.send(
                            "Your answer was correct, but I could not grant the role. "
                            "Please contact server staff."
                        )
                        return
                    await member.send(
                        f"Verified successfully in **{member.guild.name}**."
                    )
                    await self._log_success(member, role)
                    return
                remaining = 3 - attempt
                if remaining:
                    await member.send(
                        f"That code was incorrect. {remaining} attempt(s) remain."
                    )
            await member.send("Verification failed. Click Verify for a new code.")
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.info("Verification DM closed user=%s", member.id)
        finally:
            self._active_users.discard(member.id)

    async def _log_success(self, member: discord.Member, role: discord.Role) -> None:
        audit_logging = self.bot.get_cog("AuditLogging")
        if audit_logging is None:
            return
        await audit_logging.dispatch(
            member.guild,
            kind="verification_success",
            title="Member verified",
            target=f"{member} (`{member.id}`)",
            target_id=member.id,
            actor_override=member,
            reason_override=f"Granted {role.name}",
            color=discord.Color.green(),
        )

    async def _setup(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        role: discord.Role | None,
        *,
        lock_public_channels: bool,
    ) -> tuple[discord.Role, discord.Message, int]:
        if channel.guild.id != guild.id:
            raise commands.BadArgument("Choose a text channel in this server.")
        bot_member = guild.me
        if bot_member is None:
            raise commands.BotMissingPermissions(["manage_roles", "manage_channels"])
        missing = [
            name
            for name in ("manage_roles", "manage_channels")
            if not getattr(bot_member.guild_permissions, name, False)
        ]
        if missing:
            raise commands.BotMissingPermissions(missing)
        verified_role = role or discord.utils.get(guild.roles, name="Verified")
        if verified_role is None:
            verified_role = await guild.create_role(
                name="Verified", reason="Aestron verification setup"
            )
        if verified_role >= bot_member.top_role:
            raise commands.BadArgument(
                "Move my highest role above the verified role, then run setup again."
            )

        changed = 0
        if lock_public_channels:
            for target in guild.channels:
                if target.id == channel.id or isinstance(target, discord.Thread):
                    continue
                everyone = target.overwrites_for(guild.default_role)
                effective_public = target.permissions_for(
                    guild.default_role
                ).view_channel
                if not effective_public:
                    continue
                verified = target.overwrites_for(verified_role)
                everyone.view_channel = False
                verified.view_channel = True
                try:
                    await target.set_permissions(
                        guild.default_role,
                        overwrite=everyone,
                        reason="Aestron verification public-channel lock",
                    )
                    await target.set_permissions(
                        verified_role,
                        overwrite=verified,
                        reason="Aestron verified access",
                    )
                    changed += 1
                except (discord.Forbidden, discord.HTTPException):
                    LOGGER.warning(
                        "Could not lock verification channel guild=%s channel=%s",
                        guild.id,
                        target.id,
                    )

        public = channel.overwrites_for(guild.default_role)
        public.update(view_channel=True, send_messages=False, read_message_history=True)
        verified = channel.overwrites_for(verified_role)
        verified.update(
            view_channel=True, send_messages=False, read_message_history=True
        )
        await channel.set_permissions(
            guild.default_role,
            overwrite=public,
            reason="Aestron verification panel access",
        )
        await channel.set_permissions(
            verified_role,
            overwrite=verified,
            reason="Aestron verification panel access",
        )
        embed = discord.Embed(
            title=f"{guild.name} verification",
            description=(
                "Click **Verify** to receive a private CAPTCHA in your DMs. "
                "Never share the code with anyone."
            ),
            color=0x5865F2,
        )
        embed.set_footer(
            text="CAPTCHA replies are handled privately and expire automatically"
        )
        panel = await channel.send(embed=embed, view=VerificationView())
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO verification_settings "
                "(guild_id, channel_id, role_id, message_id, enabled) "
                "VALUES ($1, $2, $3, $4, TRUE) ON CONFLICT (guild_id) DO UPDATE SET "
                "channel_id = EXCLUDED.channel_id, role_id = EXCLUDED.role_id, "
                "message_id = EXCLUDED.message_id, enabled = TRUE, updated_at = NOW()",
                guild.id,
                channel.id,
                verified_role.id,
                panel.id,
            )
            await connection.execute(
                "DELETE FROM verifychannels WHERE guildid = $1", guild.id
            )
            await connection.execute(
                "INSERT INTO verifychannels (channelid, guildid) VALUES ($1, $2)",
                channel.id,
                guild.id,
            )
            await connection.execute(
                "DELETE FROM verifymsg WHERE guildid = $1", guild.id
            )
            await connection.execute(
                "INSERT INTO verifymsg (guildid, channelid, messageid) VALUES ($1, $2, $3)",
                guild.id,
                channel.id,
                panel.id,
            )
        return verified_role, panel, changed

    async def _set_access(
        self, guild: discord.Guild, channel: discord.abc.GuildChannel, *, add: bool
    ) -> discord.Role:
        config = await self._config(guild)
        if config is None:
            raise commands.BadArgument("Run verification setup first.")
        role = guild.get_role(config.role_id)
        if role is None:
            raise commands.BadArgument("The configured verified role was deleted.")
        overwrite = channel.overwrites_for(role)
        overwrite.update(
            view_channel=True if add else None,
            send_messages=True if add else None,
            read_message_history=True if add else None,
        )
        await channel.set_permissions(
            role,
            overwrite=overwrite,
            reason=f"Aestron verification access {'added' if add else 'removed'}",
        )
        return role

    @commands.cooldown(1, 10, commands.BucketType.member)
    @commands.hybrid_command(
        with_app_command=False,
        brief="Complete this server's private CAPTCHA verification.",
        description="Receive a CAPTCHA in DMs and gain the configured verified role.",
        usage="",
    )
    @commands.guild_only()
    async def verify(self, ctx: commands.Context) -> None:
        """Start verification from a prefix command."""
        await ctx.send(
            await self.begin_verification(ctx.author), ephemeral=True, delete_after=10
        )

    @commands.cooldown(1, 30, commands.BucketType.guild)
    @commands.hybrid_command(
        with_app_command=False,
        aliases=["setverificationchannel"],
        brief="Create a persistent private-CAPTCHA verification panel.",
        description=(
            "Create or reuse a verified role and post a restart-safe button. Public "
            "channels are not locked unless explicitly requested."
        ),
        usage="<channel> [role] [lock_public_channels=false]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def setupverification(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        role: discord.Role | None = None,
        lock_public_channels: bool = False,
    ) -> None:
        """Create verification through a prefix command."""
        verified_role, panel, changed = await self._setup(
            ctx.guild,
            channel,
            role,
            lock_public_channels=lock_public_channels,
        )
        await ctx.send(
            f"Verification panel created: {panel.jump_url}. Role: "
            f"{verified_role.mention}. Locked {changed} public channel(s).",
            ephemeral=True,
        )

    @commands.hybrid_command(
        with_app_command=False,
        aliases=["unsetverificationchannel"],
        brief="Disable this server's CAPTCHA verification panel.",
        description="Disable new verification attempts without rewriting channel permissions.",
        usage="",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def removeverification(self, ctx: commands.Context) -> None:
        """Disable verification through a prefix command."""
        await self._disable(ctx.guild.id)
        await ctx.send("Verification is disabled.", ephemeral=True)

    @commands.cooldown(2, 10, commands.BucketType.guild)
    @commands.hybrid_command(
        with_app_command=False,
        aliases=["verifyreadadd", "verifywriteadd"],
        brief="Grant the verified role access to one channel.",
        description="Add view, send, and history access for the configured verified role.",
        usage="<channel>",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def verifyfulladd(
        self, ctx: commands.Context, channel: discord.abc.GuildChannel
    ) -> None:
        """Grant verified access through a prefix command."""
        role = await self._set_access(ctx.guild, channel, add=True)
        await ctx.send(
            f"Granted {role.mention} access to {channel.mention}.", ephemeral=True
        )

    @commands.cooldown(2, 10, commands.BucketType.guild)
    @commands.hybrid_command(
        with_app_command=False,
        aliases=["verifyreadremove", "verifywriteremove"],
        brief="Remove the verified role's explicit access to one channel.",
        description="Reset this channel's verified-role access to inherited permissions.",
        usage="<channel>",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def verifyfullremove(
        self, ctx: commands.Context, channel: discord.abc.GuildChannel
    ) -> None:
        """Remove verified access through a prefix command."""
        role = await self._set_access(ctx.guild, channel, add=False)
        await ctx.send(
            f"Reset {role.mention} access in {channel.mention}.", ephemeral=True
        )

    @commands.hybrid_command(
        with_app_command=False,
        aliases=["verifychannels"],
        brief="Show verification configuration and accessible channels.",
        description="Show panel health, role hierarchy, and explicit verified access.",
        usage="",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def verificationchannels(self, ctx: commands.Context) -> None:
        """Show verification status through a prefix command."""
        await ctx.send(embed=await self.status_embed(ctx.guild), ephemeral=True)

    async def _disable(self, guild_id: int) -> None:
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "UPDATE verification_settings SET enabled = FALSE, updated_at = NOW() "
                "WHERE guild_id = $1",
                guild_id,
            )
            await connection.execute(
                "DELETE FROM verifychannels WHERE guildid = $1", guild_id
            )

    async def status_embed(self, guild: discord.Guild) -> discord.Embed:
        """Build a bounded verification health overview."""
        config = await self._config(guild)
        embed = discord.Embed(title="Verification status", color=0x5865F2)
        if config is None:
            embed.description = "Verification is not configured."
            return embed
        role = guild.get_role(config.role_id)
        channel = guild.get_channel(config.channel_id)
        explicit = [
            target.mention
            for target in guild.channels
            if role is not None and target.overwrites_for(role).view_channel is True
        ]
        hierarchy_ok = bool(guild.me and role and role < guild.me.top_role)
        embed.add_field(name="Enabled", value="Yes" if config.enabled else "No")
        embed.add_field(name="Panel", value=getattr(channel, "mention", "Missing"))
        embed.add_field(name="Role", value=getattr(role, "mention", "Missing"))
        embed.add_field(
            name="Role hierarchy", value="Ready" if hierarchy_ok else "Needs attention"
        )
        embed.add_field(
            name="Explicit access",
            value=" ".join(explicit)[:1024] or "No explicit verified-role channels",
            inline=False,
        )
        embed.set_footer(text="CAPTCHA input is accepted only in DMs")
        return embed

    @verification.command(
        name="setup", description="Create a persistent verification panel."
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 30, key=lambda interaction: interaction.guild_id)
    async def slash_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        role: discord.Role | None = None,
        lock_public_channels: bool = False,
    ) -> None:
        """Configure verification through slash commands."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        verified_role, panel, changed = await self._setup(
            interaction.guild,
            channel,
            role,
            lock_public_channels=lock_public_channels,
        )
        await interaction.followup.send(
            f"Panel created: {panel.jump_url}. Role: {verified_role.mention}. "
            f"Locked {changed} public channel(s).",
            ephemeral=True,
        )

    @verification.command(name="status", description="Show verification health.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(2, 10, key=lambda interaction: interaction.guild_id)
    async def slash_status(self, interaction: discord.Interaction) -> None:
        """Show verification status through slash commands."""
        await interaction.response.send_message(
            embed=await self.status_embed(interaction.guild), ephemeral=True
        )

    @verification.command(name="disable", description="Disable verification attempts.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 15, key=lambda interaction: interaction.guild_id)
    async def slash_disable(self, interaction: discord.Interaction) -> None:
        """Disable verification through slash commands."""
        await self._disable(interaction.guild_id)
        await interaction.response.send_message(
            "Verification is disabled. Existing channel overwrites were preserved.",
            ephemeral=True,
        )

    @verification.command(
        name="access", description="Add or remove verified channel access."
    )
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.cooldown(2, 10, key=lambda interaction: interaction.guild_id)
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Add access", value="add"),
            app_commands.Choice(name="Reset access", value="remove"),
        ]
    )
    async def slash_access(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        action: app_commands.Choice[str],
    ) -> None:
        """Update verified access through slash commands."""
        role = await self._set_access(
            interaction.guild, channel, add=action.value == "add"
        )
        await interaction.response.send_message(
            f"{action.name} for {role.mention} in {channel.mention}.", ephemeral=True
        )

    @verification.command(name="start", description="Start your private CAPTCHA.")
    @app_commands.checks.cooldown(2, 15, key=lambda interaction: interaction.user.id)
    async def slash_start(self, interaction: discord.Interaction) -> None:
        """Start member verification through slash commands."""
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Use this command in a server.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            await self.begin_verification(interaction.user), ephemeral=True
        )
