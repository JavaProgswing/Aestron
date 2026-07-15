import asyncio
import inspect
from importlib.metadata import version
from pathlib import Path

import discord
import wavelink

import main


def test_supported_library_versions_are_installed():
    assert version("discord.py") == "2.7.1"
    assert version("wavelink") == "3.5.2"
    assert version("mcstatus") == "14.0.0"
    assert version("PyNaCl") == "1.5.0"
    assert version("libretranslatepy") == "2.1.1"


def test_current_api_signatures_are_available():
    assert "delete_message_seconds" in inspect.signature(discord.Guild.ban).parameters
    assert "nodes" in inspect.signature(wavelink.Pool.connect).parameters
    assert inspect.iscoroutinefunction(wavelink.Playable.search)


def test_removed_discord_py_patterns_are_absent():
    root = Path(__file__).parents[1]
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            root / "main.py",
            *sorted((root / "aestron_bot").glob("*.py")),
        )
    )
    for removed_pattern in (
        ".flatten()",
        "delete_message_days",
        "datetime.utcnow()",
        "client._connection._view_store",
        "commands.core._CaseInsensitiveDict",
    ):
        assert removed_pattern not in source


def test_unsafe_legacy_and_deployment_specific_patterns_are_absent():
    root = Path(__file__).parents[1]
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            root / "main.py",
            *sorted((root / "aestron_bot").glob("*.py")),
        )
    )
    for removed_pattern in (
        "discord.com/api/webhooks",
        "CHANNEL_GIT_LOGGING_ID",
        "tempbotowners",
        "disabled_channels",
        "debug_code",
        "take_screenshot",
        "webdriver",
        "execpublic",
        "evalcode",
    ):
        assert removed_pattern not in source

    assert "192.168." not in source


def test_all_cogs_register_with_discord_py_2_7():
    async def register_cogs():
        bot = main.MyBot(command_prefix="!", intents=discord.Intents.none())
        try:
            cog_types = main.get_cog_types()
            for cog in cog_types:
                await bot.add_cog(cog(bot))
            await bot.add_cog(main.Statistics(bot, bot.statistics))
            assert len(bot.cogs) == len(cog_types) + 1
            assert len(bot.commands) > 100
            assert bot.get_command("stats") is not None
            assert bot.get_command("voicehealth") is not None
        finally:
            await bot.close()

    asyncio.run(register_cogs())
