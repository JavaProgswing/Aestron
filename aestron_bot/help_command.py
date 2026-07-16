"""Prefix help command backed by the interactive help interface."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import discord
from discord.ext import commands

from .command_docs import command_invocation
from .help_ui import (
    HelpCategory,
    InteractiveHelpView,
    build_command_help_embed,
    help_category_for,
)
from .settings import RuntimeSettings

LOGGER = logging.getLogger("aestron.help")


class AestronHelpCommand(commands.HelpCommand):
    """Render consistent bot, category, group, and command documentation."""

    def __init__(self) -> None:
        """Configure help aliases, cooldown, description, and usage."""
        attributes = {
            "cooldown": commands.CooldownMapping.from_cooldown(
                1, 5, commands.BucketType.member
            ),
            "aliases": ["commands"],
            "brief": "Show command categories or detailed command help.",
            "description": (
                "Show available command categories, or get usage and aliases for "
                "one command or category."
            ),
            "help": (
                "Show available command categories, or get usage and aliases for "
                "one command or category."
            ),
            "usage": "[command or category]",
        }
        super().__init__(command_attrs=attributes)

    def _runtime_settings(self) -> RuntimeSettings:
        """Use the bot's validated settings after environment loading."""
        settings = getattr(self.context.bot, "runtime_settings", None)
        return settings if settings is not None else RuntimeSettings.from_environment()

    def _set_footer(self, embed: discord.Embed, text: str | None = None) -> None:
        settings = self._runtime_settings()
        footer_text = text or f"Aestron v{settings.version}"
        if settings.support_server_invite:
            footer_text += f" · Support: {settings.support_server_invite}"
        embed.set_footer(
            text=footer_text,
            icon_url=str(self.context.author.display_avatar),
        )

    async def send_bot_help(self, mapping) -> None:
        """Show the category-first interactive help home page."""
        prefix = self.context.clean_prefix
        settings = self._runtime_settings()
        embed = discord.Embed(
            title="Aestron help",
            description=(
                f"Use `{prefix}help <command>` for detailed usage or "
                f"`{prefix}help <category>` to list that category's commands."
            ),
            color=discord.Color.blurple(),
        )
        command_count = 0
        grouped_commands: dict[str, tuple[str, list[commands.Command]]] = {}
        for cog, cog_commands in mapping.items():
            visible = await self.filter_commands(cog_commands, sort=True)
            if not visible:
                continue
            command_count += len(visible)
            cog_name = cog.qualified_name if cog is not None else "Other"
            category_name, summary = help_category_for(cog_name)
            if category_name not in grouped_commands:
                grouped_commands[category_name] = (summary, [])
            grouped_commands[category_name][1].extend(visible)
        categories = [
            HelpCategory(
                name=name,
                description=summary,
                commands=tuple(sorted(category_commands, key=lambda item: item.name)),
            )
            for name, (summary, category_commands) in grouped_commands.items()
        ]
        embed.add_field(
            name="Available commands",
            value=(
                f"{command_count} commands visible to you · Aestron v{settings.version}"
            ),
            inline=False,
        )
        self._set_footer(embed)
        view = InteractiveHelpView(
            bot=self.context.bot,
            author_id=getattr(self.context.author, "id", 0),
            prefix=prefix,
            home_embed=embed,
            categories=categories,
        )
        view.message = await self.context.send(embed=view.render(), view=view)

    async def send_command_help(self, command: commands.Command) -> None:
        """Show one command's syntax, aliases, cooldown, and permissions."""
        embed = build_command_help_embed(command, self.context.clean_prefix)
        destination = self.get_destination()
        self._set_footer(embed)
        usage_path = Path(f"resources/command_usages/{command.name}.gif")
        if await asyncio.to_thread(usage_path.is_file):
            embed.set_image(url=f"attachment://{command.name}.gif")
            try:
                file = discord.File(usage_path, filename=f"{command.name}.gif")
                await destination.send(embed=embed, file=file)
                return
            except (OSError, discord.HTTPException):
                LOGGER.warning(
                    "Could not send usage image command=%s",
                    command.name,
                    exc_info=True,
                )
                embed.remove_image()
        await destination.send(embed=embed)

    async def send_group_help(self, command: commands.Group) -> None:
        """Show a group and let the caller browse its visible subcommands."""
        visible = await self.filter_commands(command.commands, sort=True)
        embed = discord.Embed(
            title=f"{command.qualified_name} help",
            description=command.help or command.description,
            color=0x7C5CFC,
        )
        for child in visible[:8]:
            embed.add_field(
                name=command_invocation(child, self.context.clean_prefix),
                value=child.brief,
                inline=False,
            )
        destination = self.get_destination()
        self._set_footer(embed)
        category = HelpCategory(
            name=command.qualified_name,
            description=command.help or command.description,
            commands=tuple(visible),
        )
        view = InteractiveHelpView(
            bot=self.context.bot,
            author_id=getattr(self.context.author, "id", 0),
            prefix=self.context.clean_prefix,
            home_embed=embed,
            categories=[category],
            initial_category=category.name,
        )
        view.message = await destination.send(embed=view.render(), view=view)

    async def send_cog_help(self, cog: commands.Cog) -> None:
        """Show one cog using the same interactive category interface."""
        visible = await self.filter_commands(cog.get_commands(), sort=True)
        if not visible:
            await self.context.send(
                "No commands in this category are available to you."
            )
            return
        category = HelpCategory(
            name=cog.qualified_name,
            description=cog.description or "Commands in this category.",
            commands=tuple(visible),
        )
        home_embed = discord.Embed(
            title=f"{cog.qualified_name} help",
            description=category.description,
            color=0x7C5CFC,
        )
        self._set_footer(home_embed)
        view = InteractiveHelpView(
            bot=self.context.bot,
            author_id=getattr(self.context.author, "id", 0),
            prefix=self.context.clean_prefix,
            home_embed=home_embed,
            categories=[category],
            initial_category=category.name,
        )
        view.message = await self.context.send(embed=view.render(), view=view)
