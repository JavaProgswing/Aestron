"""Command metadata normalization and validation helpers.

Discord.py exposes separate ``brief``, ``description``, ``help``, and ``usage``
fields. Aestron uses all four in different help and error surfaces, so keeping
their fallback rules in one module prevents those surfaces from drifting.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass

from discord import app_commands
from discord.ext import commands

GENERIC_DOCUMENTATION_PREFIXES = (
    "this command can be used",
    "this command is used",
    "use the command",
)
APPLICATION_NAME_PATTERN = re.compile(r"^[a-z0-9_-]{1,32}$")
PARAMETER_DESCRIPTIONS = {
    "action": "Action to apply from the listed choices.",
    "amount": "Number of items or messages to process.",
    "category": "Optional target category in this server.",
    "channel": "Target channel; uses the current channel when optional.",
    "city": "City name, optionally including state or country.",
    "code_or_url": "Discord template code or official template URL.",
    "command": "Command name exactly as shown in help.",
    "count": "Number of results to generate within the shown limits.",
    "delete_message_seconds": "Recent message history to delete with the ban.",
    "description": "Optional bounded description for the created item.",
    "details": "Detailed, non-sensitive information to submit.",
    "dice": "Number of dice to roll.",
    "duration": "Duration such as 30m, 2h, or 1d.",
    "enabled": "Whether this feature should be enabled.",
    "expression": "Arithmetic expression to evaluate safely.",
    "feature": "Feature to configure from the listed choices.",
    "first": "First member in the comparison.",
    "ip": "Public Minecraft Java server address, optionally with a port.",
    "language": "Destination language code, such as en, hi, or es.",
    "level": "Playback volume from 0 to 150 percent.",
    "lock_public_channels": "Also restrict public channels until verification.",
    "matches": "Number of recent completed matches to analyze.",
    "member": "Target server member; defaults to you when optional.",
    "message": "Message text for this action.",
    "message_id": "Discord message ID containing the persisted item.",
    "messages_per_level": "Messages required to earn each level.",
    "mode": "Mode to apply from the listed choices.",
    "name": "Validated name shown to users.",
    "nickname": "New nickname; omit it to clear the nickname.",
    "number": "One-based recent match number.",
    "options": "Two to twenty-five comma- or pipe-separated options.",
    "position": "Queue position or playback timestamp.",
    "prefix": "New command prefix, from 1 to 10 characters.",
    "price": "Positive amount of Minecraft currency to transfer.",
    "prize": "Giveaway prize shown to entrants.",
    "query": "Song name, search terms, or supported URL.",
    "question": "Complete question to answer.",
    "reason": "Optional audit-log reason for this action.",
    "response": "Bounded response sent by the custom command.",
    "role": "Target role in this server.",
    "second": "Second member; defaults to you when optional.",
    "seconds": "Slowmode delay in seconds; use 0 to disable it.",
    "sides": "Number of sides on each die.",
    "subject": "Person, item, or topic to rate.",
    "support_role": "Role allowed to manage support tickets.",
    "template_code": "Code of a template owned by this server.",
    "text": "Bounded text to process; do not include secrets.",
    "threshold": "Number of events required to trigger enforcement.",
    "time": "Duration such as 30m, 2h, or 1d.",
    "title": "Short descriptive title.",
    "user": "Target Discord user.",
    "voice_channel": "Optional voice channel for Minecraft sound effects.",
    "window_seconds": "Rate-window length in seconds.",
    "winner_count": "Number of winners to select.",
}


@dataclass(frozen=True, slots=True)
class CommandDocumentationIssue:
    """Describe one missing or invalid command documentation field."""

    command: str
    field: str
    detail: str


def infer_usage(command: commands.Command) -> str:
    """Build readable usage placeholders from a command's clean parameters."""
    parts: list[str] = []
    for parameter in command.clean_params.values():
        name = parameter.displayed_name or parameter.name
        greedy = parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.KEYWORD_ONLY,
        }
        suffix = "..." if greedy else ""
        placeholder = f"{name}{suffix}"
        if parameter.required:
            parts.append(f"<{placeholder}>")
        else:
            default = parameter.displayed_default
            if default is None or default == "None":
                parts.append(f"[{placeholder}]")
            else:
                parts.append(f"[{placeholder}={default}]")
    return " ".join(parts)


def command_invocation(command: commands.Command, prefix: str) -> str:
    """Return the documented prefix invocation for a command."""
    usage = (command.usage or infer_usage(command)).strip()
    base = f"{prefix}{command.qualified_name}"
    return f"{base} {usage}" if usage else base


def normalize_command_metadata(bot: commands.Bot) -> None:
    """Fill safe metadata fallbacks for every currently registered command."""
    for command in bot.walk_commands():
        description = (command.description or "").strip()
        help_text = (command.help or "").strip()
        brief = (command.brief or "").strip()

        fallback = description or help_text or brief
        if not fallback:
            fallback = f"Use the {command.qualified_name} command."

        if not command.description:
            command.description = fallback
        if not command.help:
            command.help = command.description
        if not command.brief:
            command.brief = command.description.splitlines()[0][:100]
        usage = (command.usage or "").strip()
        if command.clean_params and not ({"<", "["} & set(usage)):
            command.usage = infer_usage(command)
        elif not command.clean_params:
            command.usage = ""


def _walk_application_commands(
    commands_list: list[
        app_commands.Command | app_commands.Group | app_commands.ContextMenu
    ],
):
    """Yield application groups and commands recursively."""
    for command in commands_list:
        yield command
        if isinstance(command, app_commands.Group):
            yield from _walk_application_commands(command.commands)


def normalize_application_command_metadata(bot: commands.Bot) -> None:
    """Fill concise slash-option descriptions from a reviewed vocabulary."""
    for command in _walk_application_commands(bot.tree.get_commands()):
        if isinstance(command, app_commands.ContextMenu):
            continue
        if len(command.description) > 100:
            shortened = command.description[:100].rsplit(" ", maxsplit=1)[0]
            command.description = shortened.rstrip(".,;:") + "."
        if not isinstance(command, app_commands.Command):
            continue
        for name, parameter in command._params.items():
            if str(parameter.description) == "…":
                parameter.description = PARAMETER_DESCRIPTIONS.get(
                    name, f"Value for {name.replace('_', ' ')}."
                )[:100]


def audit_application_command_metadata(
    bot: commands.Bot,
) -> list[CommandDocumentationIssue]:
    """Validate slash names, descriptions, options, and Discord root limits."""
    issues: list[CommandDocumentationIssue] = []
    roots = bot.tree.get_commands()
    if len(roots) > 100:
        issues.append(
            CommandDocumentationIssue(
                "application tree",
                "count",
                "global root commands exceed Discord's 100-command limit",
            )
        )
    for command in _walk_application_commands(roots):
        qualified_name = command.qualified_name
        if isinstance(command, app_commands.ContextMenu):
            if not 1 <= len(command.name) <= 32:
                issues.append(
                    CommandDocumentationIssue(
                        qualified_name,
                        "name",
                        "context-menu name must contain 1 to 32 characters",
                    )
                )
            continue
        if not APPLICATION_NAME_PATTERN.fullmatch(command.name):
            issues.append(
                CommandDocumentationIssue(
                    qualified_name, "name", "must be lowercase and Discord-compatible"
                )
            )
        description = command.description.strip()
        if not description or description == "…":
            issues.append(
                CommandDocumentationIssue(
                    qualified_name, "description", "description is empty or generic"
                )
            )
        elif len(description) > 100:
            issues.append(
                CommandDocumentationIssue(
                    qualified_name, "description", "description exceeds 100 characters"
                )
            )
        elif description.casefold().startswith(GENERIC_DOCUMENTATION_PREFIXES):
            issues.append(
                CommandDocumentationIssue(
                    qualified_name,
                    "description",
                    "description states no concrete outcome",
                )
            )
        if isinstance(command, app_commands.Command):
            for parameter in command.parameters:
                if not parameter.description.strip() or parameter.description == "…":
                    issues.append(
                        CommandDocumentationIssue(
                            qualified_name,
                            f"parameter:{parameter.name}",
                            "slash option has no useful description",
                        )
                    )
    return issues


def audit_command_metadata(bot: commands.Bot) -> list[CommandDocumentationIssue]:
    """Return command metadata problems suitable for tests and startup checks."""
    issues: list[CommandDocumentationIssue] = []
    seen: dict[tuple[str, str], str] = {}
    for command in bot.walk_commands():
        qualified_name = command.qualified_name
        for field in ("brief", "description", "help"):
            if not (getattr(command, field, None) or "").strip():
                issues.append(
                    CommandDocumentationIssue(
                        qualified_name, field, f"{field} is empty"
                    )
                )
            elif (
                (getattr(command, field, None) or "")
                .strip()
                .casefold()
                .startswith(GENERIC_DOCUMENTATION_PREFIXES)
            ):
                issues.append(
                    CommandDocumentationIssue(
                        qualified_name,
                        field,
                        f"{field} states no concrete outcome",
                    )
                )
        if command.clean_params and not (command.usage or "").strip():
            issues.append(
                CommandDocumentationIssue(
                    qualified_name, "usage", "parameters exist but usage is empty"
                )
            )
        elif command.clean_params and not ({"<", "["} & set(command.usage or "")):
            issues.append(
                CommandDocumentationIssue(
                    qualified_name,
                    "usage",
                    "parameter placeholders must use <required> or [optional]",
                )
            )
        invocation = command_invocation(command, "a!")
        if len(invocation) > 256:
            issues.append(
                CommandDocumentationIssue(
                    qualified_name,
                    "usage",
                    "the rendered invocation exceeds Discord's 256-character limit",
                )
            )
        if len(command.brief or "") > 1024:
            issues.append(
                CommandDocumentationIssue(
                    qualified_name,
                    "brief",
                    "the summary exceeds Discord's 1024-character field limit",
                )
            )
        for field in ("description", "help"):
            if len(getattr(command, field, "") or "") > 4096:
                issues.append(
                    CommandDocumentationIssue(
                        qualified_name,
                        field,
                        f"{field} exceeds Discord's 4096-character embed limit",
                    )
                )

        for name in (command.name, *command.aliases):
            # Command names only need to be unique among siblings. A top-level
            # ``stop`` command and ``jishaku voice stop`` are different command
            # paths, just as ``admin add`` and ``playlist add`` are. Comparing
            # leaf names globally rejects valid third-party and grouped commands.
            parent_scope = (
                command.parent.qualified_name.casefold() if command.parent else ""
            )
            key = (parent_scope, name.casefold())
            owner = seen.get(key)
            if owner is not None and owner != qualified_name:
                issues.append(
                    CommandDocumentationIssue(
                        qualified_name,
                        "name",
                        f"{name!r} is also registered by {owner}",
                    )
                )
            else:
                seen[key] = qualified_name
    return issues
