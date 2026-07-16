"""High-quality social cards with safe public interaction controls."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from io import BytesIO
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ACCENT = 0xFF4655
CARD_SIZE = (1200, 480)
FONT_PATH = Path("resources/common/consolasbold.ttf")
WELCOME_THEMES = {
    "aurora": ((10, 18, 44), (84, 62, 255), (44, 231, 194)),
    "sunset": ((44, 13, 34), (255, 70, 85), (255, 184, 77)),
    "midnight": ((4, 9, 20), (30, 64, 175), (97, 218, 251)),
}
WANTED_LEVELS = {
    "mischief": (2_500, "Minor mischief", (255, 190, 78)),
    "chaos": (10_000, "Certified chaos agent", (255, 89, 94)),
    "legendary": (50_000, "Server-wide menace", (190, 86, 255)),
}


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load the bundled typeface with a portable fallback."""
    try:
        return ImageFont.truetype(str(FONT_PATH), size)
    except OSError:
        return ImageFont.load_default()


def _gradient(
    size: tuple[int, int], start: tuple[int, int, int], end: tuple[int, int, int]
) -> Image.Image:
    """Create a smooth vertical RGB gradient without extra dependencies."""
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    height = max(size[1] - 1, 1)
    for y in range(size[1]):
        ratio = y / height
        color = tuple(round(a + (b - a) * ratio) for a, b in zip(start, end))
        draw.line((0, y, size[0], y), fill=color)
    return image


def _avatar_layer(avatar_bytes: bytes, diameter: int, border: tuple[int, int, int]):
    """Crop an avatar to a bordered circle."""
    with Image.open(BytesIO(avatar_bytes)) as source:
        avatar = ImageOps.fit(
            source.convert("RGB"), (diameter, diameter), Image.Resampling.LANCZOS
        )
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    layer = Image.new("RGBA", (diameter + 20, diameter + 20), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(
        (0, 0, diameter + 19, diameter + 19), fill=(*border, 255)
    )
    layer.paste(avatar.convert("RGBA"), (10, 10), mask)
    return layer


def _render_welcome(
    avatar_bytes: bytes,
    member_name: str,
    member_count: int,
    guild_name: str,
    theme: str,
) -> bytes:
    """Render a modern welcome card and return encoded PNG bytes."""
    dark, middle, highlight = WELCOME_THEMES[theme]
    canvas = _gradient(CARD_SIZE, dark, middle).convert("RGBA")
    with Image.open(BytesIO(avatar_bytes)) as source:
        backdrop = ImageOps.fit(
            source.convert("RGB"), CARD_SIZE, Image.Resampling.LANCZOS
        ).filter(ImageFilter.GaussianBlur(32))
    backdrop.putalpha(70)
    canvas.alpha_composite(backdrop.convert("RGBA"))
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.ellipse((830, -220, 1330, 280), fill=(*highlight, 55))
    draw.ellipse((-180, 300, 310, 790), fill=(*middle, 80))
    draw.rounded_rectangle(
        (54, 54, 1146, 426),
        radius=34,
        fill=(5, 10, 24, 188),
        outline=(*highlight, 180),
        width=3,
    )
    canvas.alpha_composite(_avatar_layer(avatar_bytes, 252, highlight), (92, 104))
    display_name = member_name[:24]
    guild_text = guild_name[:36]
    draw.text((410, 110), "WELCOME TO", font=_font(26), fill=(*highlight, 255))
    draw.text((410, 155), guild_text, font=_font(42), fill=(255, 255, 255, 255))
    draw.text((410, 235), display_name, font=_font(54), fill=(255, 255, 255, 255))
    draw.rounded_rectangle((410, 322, 770, 378), radius=18, fill=(*highlight, 50))
    draw.text(
        (432, 334),
        f"MEMBER #{member_count:,}",
        font=_font(23),
        fill=(*highlight, 255),
    )
    draw.text(
        (815, 345),
        "SAY HELLO  •  MAKE MEMORIES",
        font=_font(17),
        fill=(220, 226, 245, 255),
    )
    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


def _render_wanted(
    avatar_bytes: bytes,
    member_name: str,
    reason: str,
    level: str,
    member_id: int,
) -> tuple[bytes, int]:
    """Render a cyberpunk bounty poster with a stable reward."""
    base_reward, label, highlight = WANTED_LEVELS[level]
    bonus = (
        int.from_bytes(
            hashlib.blake2b(str(member_id).encode(), digest_size=2).digest(), "big"
        )
        % 2_500
    )
    bounty = base_reward + bonus
    canvas = _gradient(CARD_SIZE, (12, 8, 16), (62, 12, 25)).convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    for x in range(-200, 1400, 90):
        draw.line((x, 0, x - 260, 480), fill=(*highlight, 22), width=3)
    for y in range(0, 480, 8):
        draw.line((0, y, 1200, y), fill=(255, 255, 255, 8))
    draw.rounded_rectangle(
        (48, 42, 1152, 438),
        radius=24,
        fill=(8, 8, 13, 225),
        outline=(*highlight, 230),
        width=4,
    )
    draw.rectangle((48, 42, 1152, 105), fill=(*highlight, 220))
    draw.text(
        (78, 53), "AESTRON // BOUNTY NETWORK", font=_font(27), fill=(15, 10, 17, 255)
    )
    canvas.alpha_composite(_avatar_layer(avatar_bytes, 250, highlight), (85, 126))
    draw.text((405, 135), "WANTED", font=_font(67), fill=(*highlight, 255))
    draw.text((410, 215), member_name[:25], font=_font(38), fill=(255, 255, 255, 255))
    draw.text((410, 276), label.upper(), font=_font(18), fill=(207, 210, 224, 255))
    draw.text((410, 312), reason[:48], font=_font(22), fill=(255, 255, 255, 255))
    draw.rounded_rectangle((405, 365, 870, 414), radius=14, fill=(*highlight, 45))
    draw.text(
        (428, 375),
        f"BOUNTY  {bounty:,} EMERALDS",
        font=_font(22),
        fill=(*highlight, 255),
    )
    draw.text(
        (940, 370),
        f"ID {member_id % 100000:05d}",
        font=_font(17),
        fill=(180, 185, 201, 255),
    )
    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue(), bounty


class SocialCardView(discord.ui.View):
    """Let the community react once each without allowing mention spam."""

    def __init__(self, target_id: int, kind: str) -> None:
        """Create reaction counters for one target card."""
        super().__init__(timeout=300)
        self.target_id = target_id
        self.kind = kind
        self.reactors: set[int] = set()
        self.message: discord.Message | None = None
        if kind == "wanted":
            self.primary.label = "Raise bounty"
            self.primary.emoji = "💰"
            self.secondary.label = "Vouch for them"
            self.secondary.emoji = "🕊️"
        self.positive = 0
        self.secondary_count = 0

    async def _vote(self, interaction: discord.Interaction, *, secondary: bool) -> None:
        if interaction.user.id in self.reactors:
            await interaction.response.send_message(
                "You already reacted to this card.", ephemeral=True
            )
            return
        self.reactors.add(interaction.user.id)
        if secondary:
            self.secondary_count += 1
        else:
            self.positive += 1
        embed = interaction.message.embeds[0]
        if self.kind == "wanted":
            embed.set_footer(
                text=f"Bounty boosts: {self.positive} • Vouches: {self.secondary_count}"
            )
        else:
            embed.set_footer(
                text=f"Waves: {self.positive} • Party invites: {self.secondary_count}"
            )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(
        label="Wave hello", emoji="👋", style=discord.ButtonStyle.success
    )
    async def primary(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Record the primary card reaction."""
        await self._vote(interaction, secondary=False)

    @discord.ui.button(
        label="Invite to party", emoji="🎉", style=discord.ButtonStyle.primary
    )
    async def secondary(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Record the secondary card reaction."""
        await self._vote(interaction, secondary=True)

    @discord.ui.button(
        label="View profile", emoji="🔎", style=discord.ButtonStyle.secondary
    )
    async def profile(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Show concise account context privately."""
        member = (
            interaction.guild.get_member(self.target_id) if interaction.guild else None
        )
        if member is None:
            await interaction.response.send_message(
                "That member is no longer available.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"{member.mention}\nJoined: {discord.utils.format_dt(member.joined_at, 'R') if member.joined_at else 'Unknown'}\nAccount: {discord.utils.format_dt(member.created_at, 'R')}",
            ephemeral=True,
        )

    async def on_timeout(self) -> None:
        """Disable expired card controls."""
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)


class Social(commands.Cog):
    """Create high-quality social cards with community reactions."""

    social = app_commands.Group(
        name="social", description="Create interactive social cards."
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot instance."""
        self.bot = bot

    async def _welcome_card(
        self, member: discord.Member, theme: str
    ) -> tuple[discord.File, discord.Embed]:
        theme = theme.casefold()
        if theme not in WELCOME_THEMES:
            raise commands.BadArgument("Theme must be aurora, sunset, or midnight.")
        avatar_bytes = await member.display_avatar.with_size(512).read()
        image = await asyncio.to_thread(
            _render_welcome,
            avatar_bytes,
            member.display_name,
            member.guild.member_count or 0,
            member.guild.name,
            theme,
        )
        filename = f"welcome-{member.id}.png"
        embed = discord.Embed(
            title=f"A new story begins — welcome {member.display_name}!",
            description=f"Give {member.mention} a warm welcome to **{member.guild.name}**. They are member **#{member.guild.member_count or 0:,}**.",
            color=discord.Color.from_rgb(*WELCOME_THEMES[theme][2]),
        )
        embed.set_image(url=f"attachment://{filename}")
        return discord.File(BytesIO(image), filename=filename), embed

    async def _wanted_card(
        self, member: discord.Member, reason: str, level: str
    ) -> tuple[discord.File, discord.Embed]:
        reason = " ".join(reason.split())
        if not 3 <= len(reason) <= 80:
            raise commands.BadArgument("Reason must be between 3 and 80 characters.")
        level = level.casefold()
        if level not in WANTED_LEVELS:
            raise commands.BadArgument("Level must be mischief, chaos, or legendary.")
        avatar_bytes = await member.display_avatar.with_size(512).read()
        image, bounty = await asyncio.to_thread(
            _render_wanted, avatar_bytes, member.display_name, reason, level, member.id
        )
        filename = f"wanted-{member.id}.png"
        embed = discord.Embed(
            title=f"BOUNTY POSTED: {member.display_name}",
            description=f"**Charge:** {discord.utils.escape_markdown(reason)}\n**Reward:** {bounty:,} emeralds\n\nEntirely fictional. Please do not actually hunt anyone.",
            color=discord.Color.from_rgb(*WANTED_LEVELS[level][2]),
        )
        embed.set_image(url=f"attachment://{filename}")
        return discord.File(BytesIO(image), filename=filename), embed

    async def _send(
        self,
        destination,
        *,
        file: discord.File,
        embed: discord.Embed,
        target_id: int,
        kind: str,
    ):
        view = SocialCardView(target_id, kind)
        message = await destination(file=file, embed=embed, view=view)
        view.message = message

    @commands.command(
        name="welcome",
        brief="Create an interactive welcome card.",
        description="Create a generated welcome card with a selectable visual theme and public reactions.",
        usage="[member] [theme]",
    )
    @commands.guild_only()
    @commands.bot_has_permissions(attach_files=True, embed_links=True)
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def welcome_prefix(
        self,
        ctx: commands.Context,
        member: discord.Member | None = None,
        theme: str = "aurora",
    ) -> None:
        """Generate a welcome card through the configured prefix."""
        member = member or ctx.author
        file, embed = await self._welcome_card(member, theme)
        await self._send(
            ctx.send, file=file, embed=embed, target_id=member.id, kind="welcome"
        )

    @commands.command(
        name="wanted",
        brief="Create an interactive bounty poster.",
        description="Create a generated fictional bounty poster with a charge, threat level, and community reactions.",
        usage="[member] [level] [reason...]",
    )
    @commands.guild_only()
    @commands.bot_has_permissions(attach_files=True, embed_links=True)
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def wanted_prefix(
        self,
        ctx: commands.Context,
        member: discord.Member | None = None,
        level: str = "chaos",
        *,
        reason: str = "causing suspicious amounts of fun",
    ) -> None:
        """Generate a bounty poster through the configured prefix."""
        member = member or ctx.author
        file, embed = await self._wanted_card(member, reason, level)
        await self._send(
            ctx.send, file=file, embed=embed, target_id=member.id, kind="wanted"
        )

    @social.command(name="welcome", description="Generate an interactive welcome card.")
    @app_commands.choices(
        theme=[
            app_commands.Choice(name=name.title(), value=name)
            for name in WELCOME_THEMES
        ]
    )
    @app_commands.checks.bot_has_permissions(attach_files=True, embed_links=True)
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.user.id)
    async def welcome_slash(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        theme: app_commands.Choice[str] | None = None,
    ) -> None:
        """Generate a welcome card through `/social welcome`."""
        await interaction.response.defer(thinking=True)
        member = member or interaction.user
        file, embed = await self._welcome_card(
            member, theme.value if theme else "aurora"
        )
        view = SocialCardView(member.id, "welcome")
        await interaction.followup.send(file=file, embed=embed, view=view)
        view.message = await interaction.original_response()

    @social.command(
        name="wanted", description="Generate an interactive fictional bounty poster."
    )
    @app_commands.choices(
        level=[
            app_commands.Choice(name=name.title(), value=name) for name in WANTED_LEVELS
        ]
    )
    @app_commands.checks.bot_has_permissions(attach_files=True, embed_links=True)
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.user.id)
    async def wanted_slash(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        level: app_commands.Choice[str] | None = None,
        reason: str = "causing suspicious amounts of fun",
    ) -> None:
        """Generate a bounty poster through `/social wanted`."""
        await interaction.response.defer(thinking=True)
        member = member or interaction.user
        file, embed = await self._wanted_card(
            member, reason, level.value if level else "chaos"
        )
        view = SocialCardView(member.id, "wanted")
        await interaction.followup.send(file=file, embed=embed, view=view)
        view.message = await interaction.original_response()
