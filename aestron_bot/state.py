"""Mutable runtime state owned by the bot instance."""

from dataclasses import dataclass, field

from discord.ext import commands


@dataclass(slots=True)
class RuntimeState:
    """Ephemeral process state that should not live in module globals."""

    maintenance_mode: bool = False
    maintenance_reason: str = "Maintenance in progress."


def _cooldown(rate: float, per: float) -> commands.CooldownMapping:
    return commands.CooldownMapping.from_cooldown(rate, per, commands.BucketType.member)


@dataclass(slots=True)
class RateLimits:
    """Named anti-abuse limits owned by one running bot instance."""

    command_spam: commands.CooldownMapping = field(
        default_factory=lambda: _cooldown(5.0, 8.0)
    )
    message_spam: commands.CooldownMapping = field(
        default_factory=lambda: _cooldown(5.0, 8.0)
    )
    member_ban: commands.CooldownMapping = field(
        default_factory=lambda: _cooldown(2.0, 60.0)
    )
    member_unban: commands.CooldownMapping = field(
        default_factory=lambda: _cooldown(2.0, 30.0)
    )
    channel_create: commands.CooldownMapping = field(
        default_factory=lambda: _cooldown(2.0, 120.0)
    )
    channel_delete: commands.CooldownMapping = field(
        default_factory=lambda: _cooldown(2.0, 30.0)
    )
    channel_update: commands.CooldownMapping = field(
        default_factory=lambda: _cooldown(3.0, 10.0)
    )
    role_create: commands.CooldownMapping = field(
        default_factory=lambda: _cooldown(2.0, 120.0)
    )
    role_delete: commands.CooldownMapping = field(
        default_factory=lambda: _cooldown(2.0, 30.0)
    )
    role_update: commands.CooldownMapping = field(
        default_factory=lambda: _cooldown(4.0, 20.0)
    )
    guild_update: commands.CooldownMapping = field(
        default_factory=lambda: _cooldown(2.0, 240.0)
    )
    warning_repeat: commands.CooldownMapping = field(
        default_factory=lambda: _cooldown(1.0, 30.0)
    )
