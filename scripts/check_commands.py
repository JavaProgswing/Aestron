"""Validate every production command against discord.py without logging in."""

from __future__ import annotations

import asyncio

import discord

import main
from aestron_bot import (
    audit_application_command_metadata,
    audit_command_metadata,
    normalize_application_command_metadata,
    normalize_command_metadata,
)
from aestron_bot.help_command import AestronHelpCommand


async def check_commands() -> dict[str, int]:
    """Register the production cogs and fail on command documentation issues."""
    bot = main.MyBot(
        command_prefix="a!",
        intents=discord.Intents.none(),
        help_command=AestronHelpCommand(),
    )
    try:
        for cog_type in main.get_cog_types():
            await bot.add_cog(cog_type(bot))
        await bot.add_cog(main.Statistics(bot, bot.statistics))
        await bot.load_extension("jishaku")
        normalize_command_metadata(bot)
        normalize_application_command_metadata(bot)
        issues = audit_command_metadata(bot) + audit_application_command_metadata(bot)
        if issues:
            details = "\n".join(
                f"- {issue.command}.{issue.field}: {issue.detail}" for issue in issues
            )
            raise RuntimeError(f"Command validation failed:\n{details}")

        prefix_commands = list(bot.walk_commands())
        hybrid_commands = [
            command
            for command in prefix_commands
            if isinstance(command, discord.ext.commands.HybridCommand)
        ]
        return {
            "prefix_commands": len(prefix_commands),
            "hybrid_commands": len(hybrid_commands),
            "application_commands": len(bot.tree.get_commands()),
            "cogs": len(bot.cogs),
        }
    finally:
        await bot.close()


def main_entry() -> int:
    """Run validation and print its concise result."""
    result = asyncio.run(check_commands())
    print(
        "Command validation passed: "
        + ", ".join(f"{name}={value}" for name, value in result.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main_entry())
