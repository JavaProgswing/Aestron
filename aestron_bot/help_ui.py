"""Interactive, permission-aware help components for Aestron."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import discord
from discord.ext import commands

from .command_docs import command_invocation

HELP_CATEGORY_LAYOUT = (
    (
        "Start Here",
        "Bot information, help, support, feedback, and runtime statistics.",
        {
            "AestronInfo",
            "Help",
            "ServerOnboarding",
            "Support",
            "Feedback",
            "Statistics",
        },
    ),
    (
        "Safety & Moderation",
        "Moderation, AutoMod, anti-raid, verification, and audit logging.",
        {"Moderation", "AutoMod", "AntiRaid", "Captcha", "AuditLogging"},
    ),
    (
        "Server Setup",
        "Tickets, templates, custom commands, and server configuration.",
        {"Tickets", "Templates", "CustomCommands"},
    ),
    (
        "Community",
        "Profiles, social cards, giveaways, leveling, and community activities.",
        {"Community", "Social", "Giveaways", "Leveling"},
    ),
    (
        "Games & Fun",
        "Quick games, trivia, conversation starters, and Minecraft economy games.",
        {"FunGames", "MinecraftFun"},
    ),
    (
        "Music & Voice",
        "Music playback, voice diagnostics, Discord activities, and private calls.",
        {"Music", "Calls"},
    ),
    (
        "VALORANT",
        "Account linking, match history, performance analysis, and coaching.",
        {"Valorant"},
    ),
    (
        "Utilities",
        "Reminders, calculations, weather, AFK status, and other practical tools.",
        {"Misc"},
    ),
)


def help_category_for(cog_name: str) -> tuple[str, str]:
    """Map internal cog boundaries to a small user-facing category set."""
    if cog_name == "Other":
        return HELP_CATEGORY_LAYOUT[0][0], HELP_CATEGORY_LAYOUT[0][1]
    for name, description, cog_names in HELP_CATEGORY_LAYOUT:
        if cog_name in cog_names:
            return name, description
    return "Other", "Additional commands."


@dataclass(frozen=True, slots=True)
class HelpCategory:
    """One visible help category and its already-filtered commands."""

    name: str
    description: str
    commands: tuple[commands.Command, ...]


def build_command_help_embed(
    command: commands.Command,
    prefix: str,
) -> discord.Embed:
    """Build the detailed command card used by help commands and selects."""
    embed = discord.Embed(
        title=f"{command.qualified_name} help",
        description=command.help or command.description,
        color=0x7C5CFC,
    )
    embed.add_field(
        name="Usage",
        value=f"`{command_invocation(command, prefix)}`",
        inline=False,
    )
    aliases = ", ".join(f"`{alias}`" for alias in command.aliases) or "None"
    embed.add_field(name="Aliases", value=aliases, inline=False)
    if command.parent is not None:
        embed.add_field(
            name="Command group",
            value=f"`{command.parent.qualified_name}`",
            inline=False,
        )
    if isinstance(command, commands.Group) and command.commands:
        subcommands = sorted(command.commands, key=lambda child: child.name)
        embed.add_field(
            name="Subcommands",
            value="\n".join(
                f"`{command_invocation(child, prefix)}` — {child.brief}"
                for child in subcommands[:12]
            )[:1024],
            inline=False,
        )
    placeholders = command.extras.get("placeholders")
    if placeholders:
        embed.add_field(
            name="Custom placeholders",
            value=f"`{str(placeholders).replace(', ', '`, `')}`",
            inline=False,
        )
    return embed


class HelpCategorySelect(discord.ui.Select):
    """Select one visible command category."""

    def __init__(self, categories: Sequence[HelpCategory]) -> None:
        """Create options from runtime cogs rather than hardcoded categories."""
        options = [
            discord.SelectOption(
                label=category.name[:100],
                value=category.name,
                description=category.description.splitlines()[0][:100],
                emoji="📂",
            )
            for category in categories[:25]
        ]
        super().__init__(
            placeholder="Choose a command category",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Render the selected category in the existing help message."""
        menu = cast(InteractiveHelpView, self.view)
        menu.select_category(self.values[0])
        await interaction.response.edit_message(embed=menu.render(), view=menu)


class HelpCommandSelect(discord.ui.Select):
    """Open detailed help for one command on the current category page."""

    def __init__(self, command_page: Sequence[commands.Command]) -> None:
        """Create options for the commands displayed on the current page."""
        options = [
            discord.SelectOption(
                label=command.qualified_name[:100],
                value=command.qualified_name,
                description=(command.brief or command.description)[:100],
                emoji="⌨️",
            )
            for command in command_page
        ]
        super().__init__(
            placeholder="View detailed command usage",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Return command details privately without replacing the menu."""
        menu = cast(InteractiveHelpView, self.view)
        command = menu.bot.get_command(self.values[0])
        if command is None:
            await interaction.response.send_message(
                "That command is no longer registered.", ephemeral=True
            )
            return
        embed = build_command_help_embed(command, menu.prefix)
        embed.set_footer(text="This detail is visible only to you")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class InteractiveHelpView(discord.ui.View):
    """Category selection, command details, and pagination for help output."""

    page_size = 8
    category_page_size = 23

    def __init__(
        self,
        *,
        bot: commands.Bot,
        author_id: int,
        prefix: str,
        home_embed: discord.Embed,
        categories: Sequence[HelpCategory],
        initial_category: str | None = None,
    ) -> None:
        """Create a help menu from commands visible to the invoking member."""
        super().__init__(timeout=120)
        self.bot = bot
        self.author_id = author_id
        self.prefix = prefix
        self.home_embed = home_embed
        self.categories = {category.name: category for category in categories}
        self.category_order = list(self.categories)
        self.current_category = initial_category
        self.category_page = 0
        self.page = 0
        self.message: discord.Message | None = None

        if initial_category in self.category_order:
            self.category_page = self.category_order.index(initial_category) // 23
        self._refresh_category_select()
        self._refresh_command_select()
        self._refresh_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Allow only the member who opened this help menu to use it."""
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Open your own help menu to use these controls.", ephemeral=True
        )
        return False

    def select_category(self, category_name: str) -> None:
        """Select a category and reset its pagination."""
        self.current_category = category_name
        if category_name in self.category_order:
            self.category_page = (
                self.category_order.index(category_name) // self.category_page_size
            )
        self.page = 0
        self._refresh_category_select()
        self._refresh_command_select()
        self._refresh_buttons()

    def render(self) -> discord.Embed:
        """Render the home page or current category page."""
        if self.current_category is None:
            embed = self.home_embed.copy()
            pages = self._category_pages()
            for category in pages[self.category_page]:
                embed.add_field(
                    name=f"{category.name} ({len(category.commands)})",
                    value=category.description.splitlines()[0][:180],
                    inline=True,
                )
            if len(pages) > 1:
                embed.set_footer(
                    text=(
                        f"Category page {self.category_page + 1}/{len(pages)} • "
                        "Choose a category below"
                    )
                )
            return embed

        category = self.categories[self.current_category]
        pages = self._pages(category)
        command_page = pages[self.page]
        embed = discord.Embed(
            title=f"📂 {category.name}",
            description=category.description or "Commands in this category.",
            color=0x7C5CFC,
        )
        for command in command_page:
            embed.add_field(
                name=command_invocation(command, self.prefix),
                value=command.brief or command.description,
                inline=False,
            )
        embed.set_footer(
            text=(
                f"Page {self.page + 1}/{len(pages)} • "
                "Select a command below for full usage"
            )
        )
        return embed

    def _pages(self, category: HelpCategory) -> list[tuple[commands.Command, ...]]:
        commands_list = category.commands
        return [
            commands_list[index : index + self.page_size]
            for index in range(0, len(commands_list), self.page_size)
        ] or [tuple()]

    def _category_pages(self) -> list[tuple[HelpCategory, ...]]:
        categories = [self.categories[name] for name in self.category_order]
        return [
            tuple(categories[index : index + self.category_page_size])
            for index in range(0, len(categories), self.category_page_size)
        ] or [tuple()]

    def _refresh_category_select(self) -> None:
        for item in list(self.children):
            if isinstance(item, HelpCategorySelect):
                self.remove_item(item)
        category_page = self._category_pages()[self.category_page]
        if category_page:
            self.add_item(HelpCategorySelect(category_page))

    def _refresh_command_select(self) -> None:
        for item in list(self.children):
            if isinstance(item, HelpCommandSelect):
                self.remove_item(item)
        if self.current_category is None:
            return
        category = self.categories[self.current_category]
        command_page = self._pages(category)[self.page]
        if command_page:
            self.add_item(HelpCommandSelect(command_page))

    def _refresh_buttons(self) -> None:
        if self.current_category is None:
            self.home_button.disabled = True
            category_pages = self._category_pages()
            self.previous_button.disabled = self.category_page == 0
            self.next_button.disabled = self.category_page >= len(category_pages) - 1
            return
        page_count = len(self._pages(self.categories[self.current_category]))
        self.home_button.disabled = False
        self.previous_button.disabled = self.page == 0
        self.next_button.disabled = self.page >= page_count - 1

    @discord.ui.button(
        label="Home",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def home_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Return to the category overview."""
        self.current_category = None
        self.page = 0
        self._refresh_category_select()
        self._refresh_command_select()
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary, row=2)
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Move to the previous command page."""
        if self.current_category is None:
            self.category_page = max(0, self.category_page - 1)
            self._refresh_category_select()
        else:
            self.page = max(0, self.page - 1)
        self._refresh_command_select()
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, row=2)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Move to the next command page."""
        if self.current_category is None:
            self.category_page = min(
                len(self._category_pages()) - 1, self.category_page + 1
            )
            self._refresh_category_select()
        else:
            page_count = math.ceil(
                len(self.categories[self.current_category].commands) / self.page_size
            )
            self.page = min(max(0, page_count - 1), self.page + 1)
        self._refresh_command_select()
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.render(), view=self)

    async def on_timeout(self) -> None:
        """Disable expired components without deleting useful help content."""
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
