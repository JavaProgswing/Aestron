"""Prefix help command backed by the interactive help interface."""

from __future__ import annotations

import asyncio
import difflib
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from .command_docs import command_invocation
from .help_ui import (
    HELP_CATEGORY_LAYOUT,
    HelpCategory,
    InteractiveHelpView,
    build_command_help_embed,
    help_category_for,
)
from .settings import RuntimeSettings

LOGGER = logging.getLogger("aestron.help")


async def _command_is_visible(
    command: commands.Command,
    context: commands.Context,
) -> bool:
    """Return whether a prefix command is usable in an interaction context."""
    if command.hidden or not command.enabled:
        return False
    try:
        return await command.can_run(context)
    except commands.CommandError:
        return False
    except Exception:
        LOGGER.debug(
            "Command visibility check failed command=%s",
            command.qualified_name,
            exc_info=True,
        )
        return False


async def _visible_categories(
    bot: commands.Bot,
    context: commands.Context,
) -> list[HelpCategory]:
    """Build the task-based help categories visible to one interaction user."""
    grouped: dict[str, tuple[str, list[commands.Command]]] = {}
    for command in sorted(bot.commands, key=lambda item: item.qualified_name):
        if not await _command_is_visible(command, context):
            continue
        category_name, summary = help_category_for(command.cog_name or "Other")
        if category_name not in grouped:
            grouped[category_name] = (summary, [])
        grouped[category_name][1].append(command)

    return [
        HelpCategory(
            name=name,
            description=summary,
            commands=tuple(sorted(category_commands, key=lambda item: item.name)),
        )
        for name, (summary, category_commands) in grouped.items()
    ]


def _help_footer(
    embed: discord.Embed,
    settings: RuntimeSettings,
    *,
    icon_url: str | None = None,
) -> None:
    """Apply the shared version and support footer to a help response."""
    footer = f"Aestron v{settings.version}"
    if settings.support_server_invite:
        footer += f" · Support: {settings.support_server_invite}"
    embed.set_footer(text=footer, icon_url=icon_url)


async def _display_prefix(
    bot: commands.Bot,
    context: commands.Context,
    fallback: str,
) -> str:
    """Resolve the guild's configured prefix without exposing mention prefixes."""
    try:
        prefixes = await bot.get_prefix(context.message)
    except Exception:
        LOGGER.debug("Could not resolve guild prefix for slash help", exc_info=True)
        return fallback
    if isinstance(prefixes, str):
        return prefixes
    usable = [prefix for prefix in prefixes if not prefix.startswith("<@")]
    return usable[-1] if usable else fallback


class SlashHelp(commands.Cog, name="Help"):
    """Expose the interactive help browser as a real slash command."""

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot used for command discovery and permission checks."""
        self.bot = bot

    def _settings(self) -> RuntimeSettings:
        settings = getattr(self.bot, "runtime_settings", None)
        return settings if settings is not None else RuntimeSettings.from_environment()

    @app_commands.command(
        name="help",
        description="Browse command categories or view detailed command usage.",
    )
    @app_commands.describe(
        topic="Optional command or category, such as play or Safety & Moderation."
    )
    async def slash_help(
        self,
        interaction: discord.Interaction,
        topic: app_commands.Range[str, 1, 100] | None = None,
    ) -> None:
        """Show permission-aware help privately and acknowledge immediately."""
        await interaction.response.defer(ephemeral=True)
        context = await commands.Context.from_interaction(interaction)
        categories = await _visible_categories(self.bot, context)
        settings = self._settings()
        prefix = await _display_prefix(self.bot, context, settings.default_prefix)
        avatar_url = str(interaction.user.display_avatar)

        if topic:
            requested = " ".join(topic.split())
            command = self.bot.get_command(requested.casefold())
            if command is not None and await _command_is_visible(command, context):
                embed = build_command_help_embed(command, prefix)
                _help_footer(embed, settings, icon_url=avatar_url)
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            category = next(
                (
                    item
                    for item in categories
                    if item.name.casefold() == requested.casefold()
                ),
                None,
            )
            if category is None:
                candidates = [item.name for item in categories]
                candidates.extend(
                    command.qualified_name
                    for command in self.bot.walk_commands()
                    if not command.hidden
                )
                suggestions = difflib.get_close_matches(
                    requested,
                    candidates,
                    n=3,
                    cutoff=0.45,
                )
                hint = (
                    " Try " + ", ".join(f"`{item}`" for item in suggestions) + "."
                    if suggestions
                    else " Choose a category from `/help` instead."
                )
                await interaction.followup.send(
                    f"I could not find `{requested}`.{hint}",
                    ephemeral=True,
                )
                return
            initial_category = category.name
        else:
            initial_category = None

        command_count = sum(len(category.commands) for category in categories)
        embed = discord.Embed(
            title="Aestron help",
            description=(
                "Choose a category below, or use `/help topic:<command or category>` "
                "for a direct answer. Prefix users can also run "
                f"`{prefix}help`."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Available commands",
            value=f"{command_count} commands visible to you · Aestron v{settings.version}",
            inline=False,
        )
        _help_footer(embed, settings, icon_url=avatar_url)
        view = InteractiveHelpView(
            bot=self.bot,
            author_id=interaction.user.id,
            prefix=prefix,
            home_embed=embed,
            categories=categories,
            initial_category=initial_category,
        )
        view.message = await interaction.followup.send(
            embed=view.render(),
            view=view,
            ephemeral=True,
            wait=True,
        )

    @slash_help.autocomplete("topic")
    async def topic_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Suggest task categories and registered command paths."""
        del interaction
        candidates = [layout[0] for layout in HELP_CATEGORY_LAYOUT]
        candidates.extend(
            command.qualified_name
            for command in self.bot.walk_commands()
            if not command.hidden
        )
        needle = current.casefold().strip()
        matching = sorted(
            {candidate for candidate in candidates if needle in candidate.casefold()},
            key=lambda candidate: (
                not candidate.casefold().startswith(needle),
                candidate,
            ),
        )
        return [
            app_commands.Choice(name=candidate[:100], value=candidate[:100])
            for candidate in matching[:25]
        ]


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
        if text is not None:
            embed.set_footer(
                text=text,
                icon_url=str(self.context.author.display_avatar),
            )
            return
        _help_footer(
            embed,
            settings,
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
