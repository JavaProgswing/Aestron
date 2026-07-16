import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from discord.ext import commands

import main
from aestron_bot.command_docs import (
    audit_application_command_metadata,
    audit_command_metadata,
    command_invocation,
    infer_usage,
    normalize_application_command_metadata,
    normalize_command_metadata,
)
from aestron_bot.help_command import AestronHelpCommand
from aestron_bot.help_ui import (
    HelpCategorySelect,
    HelpCommandSelect,
    InteractiveHelpView,
)


def test_usage_is_inferred_from_required_optional_and_keyword_parameters():
    @commands.command()
    async def documented(ctx, required: str, optional: int = 3, *, reason: str):
        pass

    assert infer_usage(documented) == "<required> [optional=3] <reason...>"
    assert (
        command_invocation(documented, "a!")
        == "a!documented <required> [optional=3] <reason...>"
    )


def test_duplicate_leaf_names_are_valid_in_different_command_groups():
    @commands.group()
    async def music(ctx):
        pass

    @music.command(name="stop")
    async def music_stop(ctx):
        pass

    @commands.group()
    async def diagnostics(ctx):
        pass

    @diagnostics.command(name="stop")
    async def diagnostics_stop(ctx):
        pass

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    try:
        bot.add_command(music)
        bot.add_command(diagnostics)
        normalize_command_metadata(bot)

        assert audit_command_metadata(bot) == []
    finally:
        asyncio.run(bot.close())


def test_every_registered_command_has_complete_documentation():
    async def run_test():
        bot = main.MyBot(
            command_prefix="!",
            intents=discord.Intents.none(),
            help_command=AestronHelpCommand(),
        )
        try:
            for cog in main.get_cog_types():
                await bot.add_cog(cog(bot))
            await bot.add_cog(main.Statistics(bot, bot.statistics))
            normalize_command_metadata(bot)
            normalize_application_command_metadata(bot)

            assert len(list(bot.walk_commands())) >= 100
            # Related actions are grouped to stay comfortably below Discord's
            # 100 global root-command limit.
            application_roots = {command.name for command in bot.tree.get_commands()}
            assert 50 <= len(application_roots) <= 80
            assert {
                "antiraid",
                "automod",
                "community",
                "fun",
                "minecraft",
                "social",
                "valorant",
            } <= application_roots
            assert {
                "enableantiraid",
                "modsettings",
                "disallowlinks",
                "allowprofane",
                "welcomeuser",
                "wanteduser",
                "linkaccount",
                "matchanalysis",
                "balance",
                "daily",
                "weekly",
                "pay",
                "inventory",
                "shop",
                "pvp",
                "mcstatus",
            }.isdisjoint(application_roots)
            community_group = bot.tree.get_command("community")
            assert isinstance(community_group, discord.app_commands.Group)
            assert {command.name for command in community_group.commands} == {
                "chat",
                "chess",
                "profile",
                "server",
                "translate",
                "youtube",
            }
            assert bot.get_command("youtube") is not None
            assert bot.get_command("ytvideo") is None
            minecraft_group = bot.tree.get_command("minecraft")
            assert isinstance(minecraft_group, discord.app_commands.Group)
            assert {command.name for command in minecraft_group.commands} == {
                "balance",
                "daily",
                "inventory",
                "leaderboard",
                "pay",
                "pvp",
                "server",
                "shop",
                "weekly",
            }
            for command_name in (
                "ban",
                "clearwarnings",
                "kick",
                "nick",
                "softban",
                "timeout",
                "untimeout",
            ):
                assert bot.get_command(command_name) is not None
            assert audit_command_metadata(bot) == []
            assert audit_application_command_metadata(bot) == []

            help_command = bot.get_command("help")
            assert help_command is not None
            assert help_command.usage == "[command or category]"
            assert help_command.help

            for command in bot.walk_commands():
                invocation = command_invocation(command, "a!")
                assert invocation.startswith(f"a!{command.qualified_name}")
                assert len(invocation) <= 256

            channel = SimpleNamespace(send=AsyncMock())
            context = SimpleNamespace(
                bot=bot,
                clean_prefix="a!",
                author=SimpleNamespace(display_avatar="https://example.com/avatar.png"),
                channel=channel,
                send=channel.send,
            )
            help_renderer = bot.help_command
            help_renderer.context = context
            help_renderer.verify_checks = False

            await help_renderer.send_bot_help(help_renderer.get_bot_mapping())
            bot_help = channel.send.await_args.kwargs["embed"]
            bot_help_view = channel.send.await_args.kwargs["view"]
            assert bot_help.title == "Aestron help"
            category_names = {
                field.name.rsplit(" (", maxsplit=1)[0]
                for field in bot_help.fields
                if field.name != "Available commands"
            }
            assert category_names == {
                "Start Here",
                "Safety & Moderation",
                "Server Setup",
                "Community",
                "Games & Fun",
                "Music & Voice",
                "VALORANT",
                "Utilities",
            }
            assert len(bot_help.fields) <= 25
            assert len(bot_help) <= 6000
            assert isinstance(bot_help_view, InteractiveHelpView)
            assert any(
                isinstance(item, HelpCategorySelect) for item in bot_help_view.children
            )

            channel.send.reset_mock()
            await help_renderer.send_command_help(bot.get_command("play"))
            command_help = channel.send.await_args.kwargs["embed"]
            assert command_help.title == "play help"
            assert command_help.fields[0].name == "Usage"
            assert "a!play <song name or URL>" in command_help.fields[0].value

            channel.send.reset_mock()
            await help_renderer.send_cog_help(bot.get_cog("Moderation"))
            assert channel.send.await_count >= 1
            for call in channel.send.await_args_list:
                category_help = call.kwargs["embed"]
                assert len(category_help.fields) <= 25
                assert len(category_help) <= 6000
                assert any(
                    isinstance(item, HelpCommandSelect)
                    for item in call.kwargs["view"].children
                )

            custom_cog = bot.get_cog("CustomCommands")
            command_count = len(list(bot.walk_commands()))
            assert custom_cog._register_custom_command("greeting") is True
            assert custom_cog._register_custom_command("greeting") is True
            custom_command = bot.get_command("greeting")
            assert custom_command.extras["aestron_custom_command"] is True
            assert len(list(bot.walk_commands())) == command_count + 1
            assert audit_command_metadata(bot) == []
        finally:
            await bot.close()

    asyncio.run(run_test())
