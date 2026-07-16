"""Helpful, permission-aware guidance when Aestron joins a server."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

LOGGER = logging.getLogger(__name__)


def _guide_embed(guild: discord.Guild) -> discord.Embed:
    """Build a concise setup guide tailored to the current server."""
    bot_member = guild.me
    missing = []
    if bot_member is not None:
        for permission in (
            "manage_roles",
            "manage_channels",
            "manage_messages",
            "moderate_members",
            "view_audit_log",
        ):
            if not getattr(bot_member.guild_permissions, permission, False):
                missing.append(permission.replace("_", " ").title())
    embed = discord.Embed(
        title="Aestron is ready",
        description=(
            "Nothing disruptive is enabled automatically. Start with `/help`, then "
            "use the guided setup commands below. Setup responses are private to "
            "the administrator running them."
        ),
        color=0x5865F2,
    )
    embed.add_field(
        name="Recommended order",
        value=(
            "1. `/logs setup` — choose an audit channel\n"
            "2. `/automod setup` — configure several channels together\n"
            "3. `/verification setup` — review role-gated channel access\n"
            "4. `/ticket setup` — create a support panel and safe defaults"
        ),
        inline=False,
    )
    embed.add_field(
        name="Useful checks",
        value=(
            "`/logs overview` shows safety, verification, ticket, and logging health.\n"
            "`/automod status` and `/verification status` explain missing permissions."
        ),
        inline=False,
    )
    if "COMMUNITY" in guild.features:
        embed.add_field(
            name="Community Onboarding detected",
            value=(
                "Discord requires Onboarding default channels to remain public. "
                "Verification setup detects and reports those exceptions instead "
                "of leaving a partial, unexplained configuration."
            ),
            inline=False,
        )
    embed.add_field(
        name="Permission health",
        value=(
            "Ready for guided setup"
            if not missing
            else "Optional features need: " + ", ".join(missing)
        ),
        inline=False,
    )
    embed.set_footer(text="Use the buttons for short explanations of each setup")
    return embed


class ServerGuideView(discord.ui.View):
    """Persistent guide buttons usable by server managers after restarts."""

    def __init__(self) -> None:
        """Create restart-safe buttons with stable custom identifiers."""
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Limit setup explanations to members who can manage the server."""
        member = interaction.user
        if isinstance(member, discord.Member) and member.guild_permissions.manage_guild:
            return True
        await interaction.response.send_message(
            "This setup guide is available to members with Manage Server.",
            ephemeral=True,
        )
        return False

    @staticmethod
    async def _explain(
        interaction: discord.Interaction, title: str, description: str
    ) -> None:
        embed = discord.Embed(title=title, description=description, color=0x5865F2)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="AutoMod",
        style=discord.ButtonStyle.secondary,
        custom_id="aestron:guide:automod:v1",
    )
    async def automod(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Explain bulk AutoMod configuration privately."""
        await self._explain(
            interaction,
            "AutoMod setup",
            "Run `/automod setup`. Choose filters and thresholds in the command, "
            "then select up to 25 text, announcement, forum/media, voice, or stage "
            "channels. Forum policies also cover messages inside their posts.",
        )

    @discord.ui.button(
        label="Verification",
        style=discord.ButtonStyle.secondary,
        custom_id="aestron:guide:verification:v1",
    )
    async def verification(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Explain guided verification configuration privately."""
        await self._explain(
            interaction,
            "Verification setup",
            "Run `/verification setup` in the panel channel. Aestron creates or "
            "reuses a Verified role, auto-selects currently public channels, and "
            "shows the complete permission plan before applying it.",
        )

    @discord.ui.button(
        label="Tickets",
        style=discord.ButtonStyle.secondary,
        custom_id="aestron:guide:tickets:v1",
    )
    async def tickets(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Explain safe ticket defaults privately."""
        await self._explain(
            interaction,
            "Ticket setup",
            "Run `/ticket setup` in a text, announcement, forum, or media channel. "
            "Only the panel destination is required; Aestron can create the Support "
            "Team role, Support Tickets category, and private ticket log for you.",
        )

    @discord.ui.button(
        label="Safety overview",
        style=discord.ButtonStyle.primary,
        custom_id="aestron:guide:overview:v1",
    )
    async def overview(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Explain the consolidated safety overview privately."""
        await self._explain(
            interaction,
            "Server safety overview",
            "Configure `/logs setup`, then use `/logs overview` whenever you need a "
            "single health check for logging, anti-raid, AutoMod, verification, "
            "tickets, and giveaways.",
        )


class ServerOnboarding(commands.Cog):
    """Send and reproduce Aestron's administrator setup guide."""

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot and register no guild-specific state."""
        self.bot = bot

    async def cog_load(self) -> None:
        """Register guide buttons so old join messages survive restarts."""
        self.bot.add_view(ServerGuideView())

    @staticmethod
    def _destination(guild: discord.Guild) -> discord.TextChannel | None:
        candidates = [guild.system_channel, guild.rules_channel]
        candidates.extend(guild.text_channels)
        for channel in candidates:
            if channel is None or guild.me is None:
                continue
            permissions = channel.permissions_for(guild.me)
            if (
                permissions.view_channel
                and permissions.send_messages
                and permissions.embed_links
            ):
                return channel
        return None

    async def _send_guide(self, guild: discord.Guild) -> discord.Message | None:
        destination = self._destination(guild)
        embed = _guide_embed(guild)
        if destination is not None:
            return await destination.send(embed=embed, view=ServerGuideView())
        owner = guild.owner
        if owner is not None:
            try:
                return await owner.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass
        LOGGER.warning("No destination available for server guide guild=%s", guild.id)
        return None

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Send one non-invasive administrator guide after joining."""
        try:
            await self._send_guide(guild)
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.exception("Could not send server guide guild=%s", guild.id)

    @commands.hybrid_command(
        name="serverguide",
        aliases=["setupguide", "botguide"],
        brief="Show Aestron's recommended server setup.",
        description=(
            "Show a permission-aware guide for AutoMod, verification, tickets, "
            "logging, and server safety."
        ),
        usage="",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.cooldown(2, 20, commands.BucketType.guild)
    async def serverguide(self, ctx: commands.Context) -> None:
        """Show the same concise guide available when the bot joins."""
        await ctx.send(embed=_guide_embed(ctx.guild), view=ServerGuideView())
