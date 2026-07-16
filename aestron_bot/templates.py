"""Safe Discord server-template management."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

LOGGER = logging.getLogger(__name__)


def _template_code(value: str) -> str:
    """Extract a Discord template code from a code or supported URL."""
    value = value.strip()
    if not value:
        raise commands.BadArgument("Provide a Discord template code or URL.")
    if "://" in value:
        parsed = urlparse(value)
        if parsed.hostname not in {"discord.new", "discord.com", "www.discord.com"}:
            raise commands.BadArgument(
                "Only official Discord template URLs are accepted."
            )
        value = parsed.path.rstrip("/").rsplit("/", maxsplit=1)[-1]
    if not value or len(value) > 100 or not value.replace("-", "").isalnum():
        raise commands.BadArgument("That Discord template code is invalid.")
    return value


def _template_embed(template: discord.Template) -> discord.Embed:
    """Render bounded, non-destructive template details."""
    source = template.source_guild
    embed = discord.Embed(
        title=template.name,
        description=template.description or "No description provided.",
        color=0x5865F2,
        url=f"https://discord.new/{template.code}",
    )
    embed.add_field(name="Code", value=f"`{template.code}`")
    embed.add_field(name="Uses", value=str(template.usage_count))
    embed.add_field(name="Source", value=f"{source.name} (`{source.id}`)", inline=False)
    embed.add_field(name="Channels", value=str(len(source.channels)))
    embed.add_field(name="Roles", value=str(len(source.roles)))
    embed.set_footer(
        text="Opening a template creates a new server; it does not overwrite this one."
    )
    return embed


class Templates(commands.Cog):
    """Create, inspect, sync, and delete Discord server templates safely."""

    template = app_commands.Group(
        name="template", description="Manage Discord server templates safely."
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot used for Discord template API calls."""
        self.bot = bot
        self._mutation_locks: dict[int, asyncio.Lock] = {}

    def _lock(self, guild_id: int) -> asyncio.Lock:
        return self._mutation_locks.setdefault(guild_id, asyncio.Lock())

    async def _create_backup(
        self, guild: discord.Guild, description: str | None = None
    ) -> discord.Template:
        """Create the guild template or refresh Discord's single existing one."""
        name = f"{guild.name} backup"[:100]
        template_description = (description or "Aestron server backup")[:120]
        templates = await guild.templates()
        if templates:
            synced = await templates[0].sync()
            return await synced.edit(
                name=name,
                description=template_description,
            )

        try:
            return await guild.create_template(
                name=name,
                description=template_description,
            )
        except discord.HTTPException as error:
            # Another process may create the one allowed guild template after
            # our initial lookup. Recover from that race instead of surfacing
            # Discord error 30031 to the command user.
            if error.code != 30031:
                raise
            templates = await guild.templates()
            if not templates:
                raise
            synced = await templates[0].sync()
            return await synced.edit(
                name=name,
                description=template_description,
            )

    async def _owned_template(
        self, guild: discord.Guild, code: str
    ) -> discord.Template:
        normalized = _template_code(code).casefold()
        template = discord.utils.find(
            lambda item: item.code.casefold() == normalized, await guild.templates()
        )
        if template is None:
            raise commands.BadArgument(
                "That template is not owned by this server. Use template preview for external templates."
            )
        return template

    @commands.cooldown(1, 30, commands.BucketType.guild)
    @commands.hybrid_command(
        with_app_command=False,
        aliases=["genbackuptemplate", "backup"],
        brief="Create or refresh this server's private backup template.",
        description=(
            "Create the server's Discord template, or refresh its existing template "
            "from the current channels, roles, and settings. Discord allows one "
            "template per server."
        ),
        usage="[description]",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_guild=True)
    async def backuptemplate(
        self, ctx: commands.Context, *, description: str | None = None
    ) -> None:
        """Create or refresh a backup and deliver its URL privately when possible."""
        lock = self._lock(ctx.guild.id)
        if lock.locked():
            raise commands.MaxConcurrencyReached(1, commands.BucketType.guild)
        async with lock:
            template = await self._create_backup(ctx.guild, description)
        embed = _template_embed(template)
        try:
            await ctx.author.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            await ctx.send(
                "I created the backup, but your DMs are closed. Use `/template list` "
                "to retrieve it privately.",
                ephemeral=True,
            )
            return
        await ctx.send(
            "Backup template refreshed and sent to your DMs.", ephemeral=True
        )

    @commands.cooldown(2, 20, commands.BucketType.member)
    @commands.hybrid_command(
        with_app_command=False,
        aliases=["previewtemplate"],
        brief="Preview a Discord template without changing this server.",
        description=(
            "Inspect a template and receive its discord.new link. This command never "
            "deletes or replaces channels or roles."
        ),
        usage="<template code or URL>",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def settemplate(self, ctx: commands.Context, template: str) -> None:
        """Safely preview the template old versions attempted to apply destructively."""
        fetched = await self.bot.fetch_template(_template_code(template))
        await ctx.send(embed=_template_embed(fetched), ephemeral=True)

    @template.command(
        name="backup", description="Create or refresh the server backup template."
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 30, key=lambda interaction: interaction.guild_id)
    async def slash_backup(
        self, interaction: discord.Interaction, description: str | None = None
    ) -> None:
        """Create or refresh the server backup through slash commands."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        lock = self._lock(interaction.guild_id)
        if lock.locked():
            await interaction.followup.send(
                "Another template change is already running for this server.",
                ephemeral=True,
            )
            return
        async with lock:
            template = await self._create_backup(interaction.guild, description)
        await interaction.followup.send(embed=_template_embed(template), ephemeral=True)

    @template.command(name="list", description="List templates owned by this server.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_list(self, interaction: discord.Interaction) -> None:
        """List owned templates without exposing them publicly."""
        await interaction.response.defer(ephemeral=True)
        templates = await interaction.guild.templates()
        embed = discord.Embed(title="Server templates", color=0x5865F2)
        embed.description = (
            "\n".join(
                f"[`{item.code}`](https://discord.new/{item.code}) · {item.name} · "
                f"{item.usage_count} use(s)"
                for item in templates[:25]
            )
            or "No templates exist yet."
        )[:4096]
        await interaction.followup.send(embed=embed, ephemeral=True)

    @template.command(
        name="preview", description="Inspect any Discord template safely."
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_preview(
        self, interaction: discord.Interaction, code_or_url: str
    ) -> None:
        """Preview a template through slash commands."""
        await interaction.response.defer(ephemeral=True)
        template = await self.bot.fetch_template(_template_code(code_or_url))
        await interaction.followup.send(embed=_template_embed(template), ephemeral=True)

    @template.command(name="sync", description="Sync an owned template to this server.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 15, key=lambda interaction: interaction.guild_id)
    async def slash_sync(
        self, interaction: discord.Interaction, template_code: str
    ) -> None:
        """Refresh an existing owned template from current server state."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        lock = self._lock(interaction.guild_id)
        if lock.locked():
            await interaction.followup.send(
                "Another template change is already running for this server.",
                ephemeral=True,
            )
            return
        async with lock:
            template = await self._owned_template(interaction.guild, template_code)
            synced = await template.sync()
        await interaction.followup.send(embed=_template_embed(synced), ephemeral=True)

    @template.command(name="delete", description="Delete an owned server template.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 30, key=lambda interaction: interaction.guild_id)
    async def slash_delete(
        self, interaction: discord.Interaction, template_code: str
    ) -> None:
        """Delete one explicitly selected owned template."""
        lock = self._lock(interaction.guild_id)
        if lock.locked():
            await interaction.response.send_message(
                "Another template change is already running for this server.",
                ephemeral=True,
            )
            return
        async with lock:
            template = await self._owned_template(interaction.guild, template_code)
            await template.delete()
        await interaction.response.send_message(
            f"Deleted template `{template.code}`.", ephemeral=True
        )
