"""Unified Discord suggestion and bug-report commands."""

from __future__ import annotations

import logging
from typing import Literal

import aiohttp
import discord
from discord.ext import commands

LOGGER = logging.getLogger(__name__)


class Feedback(commands.Cog):
    """Send validated suggestions and bug reports to one review queue."""

    def __init__(self, bot: commands.Bot) -> None:
        """Bind the shared bot session and runtime settings."""
        self.bot = bot

    async def _submit(
        self,
        ctx: commands.Context,
        *,
        kind: Literal["suggestion", "bug"],
        title: str,
        details: str,
    ) -> None:
        title = " ".join(title.split())
        details = details.strip()
        if not 4 <= len(title) <= 120:
            await ctx.send("The title must be 4 to 120 characters.", ephemeral=True)
            return
        if not 15 <= len(details) <= 4000:
            await ctx.send("Details must be 15 to 4,000 characters.", ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        settings = self.bot.runtime_settings
        submitted = False
        if settings.site_base_url and settings.aestron_service_token:
            submitted = await self._submit_to_api(
                kind=kind,
                title=title,
                details=details,
                discord_user_id=ctx.author.id,
            )
        if not submitted:
            submitted = await self._submit_to_channel(
                ctx, kind=kind, title=title, details=details
            )
        if not submitted:
            await ctx.send(
                "Feedback delivery is not configured right now. Please use the "
                "support server and try again later.",
                ephemeral=True,
            )
            return
        LOGGER.info(
            "Feedback submitted kind=%s user_id=%s guild_id=%s",
            kind,
            ctx.author.id,
            ctx.guild.id if ctx.guild else None,
        )
        await ctx.send(
            "Thanks—your suggestion was submitted."
            if kind == "suggestion"
            else "Thanks—your bug report was submitted.",
            ephemeral=True,
        )

    async def _submit_to_api(
        self,
        *,
        kind: str,
        title: str,
        details: str,
        discord_user_id: int,
    ) -> bool:
        settings = self.bot.runtime_settings
        try:
            async with self.bot.session.post(
                f"{settings.site_base_url}/api/v1/bot/feedback",
                headers={
                    "X-Aestron-Service-Token": settings.aestron_service_token or ""
                },
                json={
                    "kind": kind,
                    "title": title,
                    "body": details,
                    "discord_user_id": discord_user_id,
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status == 201:
                    return True
                LOGGER.warning("Feedback API returned status=%s", response.status)
        except (aiohttp.ClientError, TimeoutError):
            LOGGER.exception("Feedback API request failed")
        return False

    async def _submit_to_channel(
        self,
        ctx: commands.Context,
        *,
        kind: str,
        title: str,
        details: str,
    ) -> bool:
        settings = self.bot.runtime_settings
        channel_id = settings.feedback_channel_id or settings.bug_logging_channel_id
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if channel is None or not hasattr(channel, "send"):
            return False
        embed = discord.Embed(
            title=f"{kind.title()}: {title}",
            description=details,
            color=discord.Color.orange()
            if kind == "suggestion"
            else discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Author", value=f"{ctx.author} (`{ctx.author.id}`)")
        if ctx.guild:
            embed.add_field(name="Guild", value=f"{ctx.guild.name} (`{ctx.guild.id}`)")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            LOGGER.exception("Could not post feedback to Discord channel")
            return False
        return True

    @commands.hybrid_command(
        brief="Send a feature or improvement suggestion.",
        description="Submits a suggestion to Aestron's shared feedback queue.",
        usage='"short title" detailed suggestion',
    )
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def suggest(self, ctx: commands.Context, title: str, *, details: str) -> None:
        """Submit one suggestion with a concise title and useful detail."""
        await self._submit(ctx, kind="suggestion", title=title, details=details)

    @commands.hybrid_command(
        brief="Report a reproducible Aestron problem.",
        description="Submits a bug report to Aestron's shared feedback queue.",
        usage='"affected command or feature" steps, expected result, and actual result',
    )
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def reportbug(
        self, ctx: commands.Context, title: str, *, details: str
    ) -> None:
        """Submit one bug report with reproduction details."""
        await self._submit(ctx, kind="bug", title=title, details=details)
