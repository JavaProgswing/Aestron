"""Polished social image commands with grouped slash-command support."""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

ACCENT = 0xFF4655
RESOURCE_ROOT = Path("resources")


def _render_welcome(
    avatar_bytes: bytes,
    member_name: str,
    member_count: int,
    guild_name: str,
) -> bytes:
    """Render one welcome card and return encoded JPEG bytes."""
    with Image.open(RESOURCE_ROOT / "welcomeuser" / "background.jpg") as source:
        background = source.convert("RGB")
    with Image.open(BytesIO(avatar_bytes)) as avatar_source:
        avatar = avatar_source.convert("RGB").resize(
            (170, 170), Image.Resampling.LANCZOS
        )
    background.paste(avatar, (388, 195))
    draw = ImageDraw.Draw(background)
    font = ImageFont.truetype(str(RESOURCE_ROOT / "common" / "consolasbold.ttf"), 18)
    text = f"Welcome {member_name}, member {member_count} of {guild_name}!"
    draw.text((8, 465), text[:92], (255, 255, 255), font=font)
    output = BytesIO()
    background.save(output, format="JPEG", quality=92, optimize=True)
    return output.getvalue()


def _render_wanted(avatar_bytes: bytes) -> bytes:
    """Render one wanted poster and return encoded JPEG bytes."""
    with Image.open(RESOURCE_ROOT / "wanteduser" / "background.jpg") as source:
        background = source.convert("RGB")
    with Image.open(BytesIO(avatar_bytes)) as avatar_source:
        avatar = avatar_source.convert("RGB").resize(
            (139, 172), Image.Resampling.LANCZOS
        )
    background.paste(avatar, (114, 153))
    output = BytesIO()
    background.save(output, format="JPEG", quality=92, optimize=True)
    return output.getvalue()


class Social(commands.Cog):
    """Create shareable welcome cards and wanted posters."""

    social = app_commands.Group(
        name="social", description="Create playful social image cards."
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot instance."""
        self.bot = bot

    async def _welcome_card(
        self, member: discord.Member
    ) -> tuple[discord.File, discord.Embed]:
        avatar_bytes = await member.display_avatar.read()
        image = await asyncio.to_thread(
            _render_welcome,
            avatar_bytes,
            member.display_name,
            member.guild.member_count or 0,
            member.guild.name,
        )
        filename = f"welcome-{member.id}.jpg"
        embed = discord.Embed(
            title=f"Welcome, {member.display_name}! 👋",
            description=f"You are member **#{member.guild.member_count or 0:,}**.",
            color=ACCENT,
        )
        embed.set_image(url=f"attachment://{filename}")
        embed.set_footer(text=member.guild.name)
        return discord.File(BytesIO(image), filename=filename), embed

    async def _wanted_card(
        self, member: discord.Member
    ) -> tuple[discord.File, discord.Embed]:
        avatar_bytes = await member.display_avatar.read()
        image = await asyncio.to_thread(_render_wanted, avatar_bytes)
        filename = f"wanted-{member.id}.jpg"
        embed = discord.Embed(
            title=f"WANTED: {member.display_name}",
            description="Last seen causing suspicious amounts of fun.",
            color=ACCENT,
        )
        embed.set_image(url=f"attachment://{filename}")
        return discord.File(BytesIO(image), filename=filename), embed

    @commands.hybrid_command(
        name="welcome",
        with_app_command=False,
        brief="Create a welcome card for a member.",
        description="Create and share a custom welcome card for a server member.",
        usage="[member]",
    )
    @commands.guild_only()
    @commands.bot_has_permissions(attach_files=True, embed_links=True)
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def welcome_prefix(
        self, ctx: commands.Context, member: discord.Member | None = None
    ) -> None:
        """Create a public welcome card from a prefix command."""
        file, embed = await self._welcome_card(member or ctx.author)
        await ctx.send(file=file, embed=embed)

    @commands.hybrid_command(
        name="wanted",
        with_app_command=False,
        brief="Put a member on a playful wanted poster.",
        description="Create and share a playful wanted poster for a server member.",
        usage="[member]",
    )
    @commands.guild_only()
    @commands.bot_has_permissions(attach_files=True, embed_links=True)
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def wanted_prefix(
        self, ctx: commands.Context, member: discord.Member | None = None
    ) -> None:
        """Create a public wanted poster from a prefix command."""
        file, embed = await self._wanted_card(member or ctx.author)
        await ctx.send(file=file, embed=embed)

    @social.command(name="welcome", description="Create a welcome card for a member.")
    @app_commands.checks.bot_has_permissions(attach_files=True, embed_links=True)
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.user.id)
    async def welcome_slash(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        """Create a public welcome card from `/social welcome`."""
        await interaction.response.defer(thinking=True)
        file, embed = await self._welcome_card(member or interaction.user)
        await interaction.followup.send(file=file, embed=embed)

    @social.command(name="wanted", description="Create a wanted poster for a member.")
    @app_commands.checks.bot_has_permissions(attach_files=True, embed_links=True)
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.user.id)
    async def wanted_slash(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        """Create a public wanted poster from `/social wanted`."""
        await interaction.response.defer(thinking=True)
        file, embed = await self._wanted_card(member or interaction.user)
        await interaction.followup.send(file=file, embed=embed)
