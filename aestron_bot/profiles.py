"""Bounded, fast Discord member profile rendering."""

from __future__ import annotations

import contextlib

import discord
from discord.ext import commands

DANGEROUS_PERMISSIONS = (
    ("administrator", "Administrator"),
    ("manage_guild", "Manage Server"),
    ("manage_roles", "Manage Roles"),
    ("manage_channels", "Manage Channels"),
    ("manage_webhooks", "Manage Webhooks"),
    ("ban_members", "Ban Members"),
    ("kick_members", "Kick Members"),
)


def _public_badges(user: discord.abc.User) -> str:
    flags = user.public_flags
    labels = []
    for attribute, label in (
        ("staff", "Discord Staff"),
        ("partner", "Partner"),
        ("hypesquad", "HypeSquad"),
        ("hypesquad_bravery", "Bravery"),
        ("hypesquad_brilliance", "Brilliance"),
        ("hypesquad_balance", "Balance"),
        ("bug_hunter", "Bug Hunter"),
        ("bug_hunter_level_2", "Bug Hunter II"),
        ("verified_bot_developer", "Early Verified Bot Developer"),
        ("active_developer", "Active Developer"),
    ):
        if getattr(flags, attribute, False):
            labels.append(label)
    return ", ".join(labels) or "None visible"


async def build_profile_embed(
    bot: commands.Bot,
    user: discord.Member | discord.User,
    guild: discord.Guild | None,
) -> discord.Embed:
    """Build a bounded profile without scanning bans or making vote API calls."""
    color = user.color if isinstance(user, discord.Member) else discord.Color.blurple()
    if not color.value:
        color = discord.Color.blurple()
    embed = discord.Embed(
        title=user.display_name,
        description=f"{user.mention}\n`{user.id}`",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(
        name="Account created",
        value=discord.utils.format_dt(user.created_at, "F")
        + f"\n({discord.utils.format_dt(user.created_at, 'R')})",
        inline=False,
    )
    embed.add_field(name="Account type", value="Bot" if user.bot else "User")
    embed.add_field(name="Public badges", value=_public_badges(user), inline=False)

    if isinstance(user, discord.Member) and guild is not None:
        position = "Owner" if user.id == guild.owner_id else "Member"
        if user.guild_permissions.administrator and position != "Owner":
            position = "Administrator"
        elif user.guild_permissions.manage_guild and position == "Member":
            position = "Moderator"
        embed.add_field(name="Server position", value=position)
        embed.add_field(
            name="Joined server",
            value=(
                discord.utils.format_dt(user.joined_at, "F")
                + f"\n({discord.utils.format_dt(user.joined_at, 'R')})"
                if user.joined_at
                else "Unavailable"
            ),
            inline=False,
        )
        roles = [role for role in reversed(user.roles) if role != guild.default_role]
        role_text = " ".join(role.mention for role in roles[:12]) or "No roles"
        if len(roles) > 12:
            role_text += f"\n…and {len(roles) - 12} more"
        embed.add_field(name=f"Roles ({len(roles)})", value=role_text, inline=False)
        dangerous = [
            label
            for attribute, label in DANGEROUS_PERMISSIONS
            if getattr(user.guild_permissions, attribute, False)
        ]
        embed.add_field(
            name="Sensitive permissions",
            value=", ".join(dangerous) or "None",
            inline=False,
        )
        embed.add_field(
            name="Communication timeout",
            value=(
                discord.utils.format_dt(user.timed_out_until, "R")
                if user.timed_out_until
                else "Not timed out"
            ),
        )

    banner = getattr(user, "banner", None)
    if banner is None:
        # Discord Member objects often lack banner data until the user is fetched.
        with contextlib.suppress(discord.NotFound, discord.HTTPException):
            banner = (await bot.fetch_user(user.id)).banner
    if banner is not None:
        embed.set_image(url=banner.url)
    embed.set_footer(text="Profile data is sourced from Discord")
    return embed
