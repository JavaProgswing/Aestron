"""Command metadata normalization and validation helpers.

Discord.py exposes separate ``brief``, ``description``, ``help``, and ``usage``
fields. Aestron uses all four in different help and error surfaces, so keeping
their fallback rules in one module prevents those surfaces from drifting.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from discord.ext import commands


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
