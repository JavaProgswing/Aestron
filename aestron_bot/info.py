"""Bot information and command-usage guides."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import discord
import psutil
from discord.ext import commands

from .command_docs import command_invocation


class AestronInfo(commands.Cog):
    """Show deployment information and detailed command usage."""

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot used to inspect commands and runtime state."""
        self.bot = bot

    @commands.hybrid_command(
        name="usage",
        brief="Show the visual usage guide for a command.",
        description="Look up a command and show its current usage guide when available.",
        usage="<command>",
    )
    @commands.cooldown(2, 5, commands.BucketType.user)
    async def command_usage(self, ctx: commands.Context, command: str) -> None:
        """Show validated help and optional demonstration images."""
        requested = self.bot.get_command(command)
        if requested is None or requested.hidden:
            raise commands.BadArgument(
                "That command was not found. Use the interactive help menu first."
            )
        invocation = command_invocation(requested, ctx.clean_prefix)
        aliases = ", ".join(f"`{alias}`" for alias in requested.aliases) or "None"
        base_embed = discord.Embed(
            title=f"{requested.qualified_name} usage",
            description=requested.help or requested.description,
            color=discord.Color.blurple(),
        )
        base_embed.add_field(name="Usage", value=f"`{invocation}`", inline=False)
        base_embed.add_field(name="Aliases", value=aliases, inline=False)

        usage_directory = Path("resources/command_usages")
        paths = await asyncio.to_thread(
            lambda: [
                path
                for path in (
                    usage_directory / f"{requested.name}.gif",
                    *(
                        usage_directory / f"{requested.name}_{index}.gif"
                        for index in range(1, 9)
                    ),
                )
                if path.is_file()
            ]
        )
        if not paths:
            await ctx.send(embed=base_embed, ephemeral=True)
            return
        embeds: list[discord.Embed] = []
        files: list[discord.File] = []
        for index, path in enumerate(paths, start=1):
            embed = base_embed.copy()
            embed.set_footer(text=f"Example {index} of {len(paths)}")
            embed.set_image(url=f"attachment://{path.name}")
            embeds.append(embed)
            files.append(discord.File(path, filename=path.name))
        await ctx.send(embeds=embeds, files=files, ephemeral=True)

    @commands.hybrid_command(
        name="botinfo",
        aliases=["info"],
        brief="Show Aestron's runtime and deployment information.",
        description="Show bot uptime, latency, version, guild count, and useful links.",
        usage="",
    )
    @commands.cooldown(2, 10, commands.BucketType.user)
    async def info_command(self, ctx: commands.Context) -> None:
        """Show bounded process and Discord runtime statistics."""
        settings = self.bot.runtime_settings
        launched_at = getattr(self.bot, "launch_time", discord.utils.utcnow())
        uptime = discord.utils.utcnow() - launched_at
        total_seconds = max(0, int(uptime.total_seconds()))
        days, remainder = divmod(total_seconds, 86_400)
        hours, remainder = divmod(remainder, 3_600)
        minutes, seconds = divmod(remainder, 60)
        embed = discord.Embed(
            title=str(self.bot.user or "Aestron"),
            description=(
                "Community safety, moderation, music, games, and opt-in "
                "performance insights."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Version", value=f"`{settings.version}`")
        embed.add_field(name="Guilds", value=f"{len(self.bot.guilds):,}")
        embed.add_field(
            name="Members",
            value=f"{sum(guild.member_count or 0 for guild in self.bot.guilds):,}",
        )
        embed.add_field(name="Gateway", value=f"{self.bot.latency * 1000:.0f} ms")
        embed.add_field(name="CPU", value=f"{psutil.cpu_percent():.1f}%")
        embed.add_field(name="Memory", value=f"{psutil.virtual_memory().percent:.1f}%")
        embed.add_field(
            name="Uptime",
            value=f"{days}d {hours}h {minutes}m {seconds}s",
            inline=False,
        )
        if os.getenv("DBL_TOKEN") and self.bot.user:
            embed.add_field(
                name="Top.gg",
                value=f"https://top.gg/bot/{self.bot.user.id}",
                inline=False,
            )
        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await ctx.send(embed=embed, ephemeral=True)
