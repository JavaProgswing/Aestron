"""Regression tests for moderation, anti-raid, logging, and tickets."""

import inspect
from types import SimpleNamespace

import discord

import main
from aestron_bot.antiraid import DANGEROUS_ACTIONS, AntiRaid
from aestron_bot.audit_logging import AuditLogging
from aestron_bot.automod import (
    LINK_PATTERN,
    SPAM_MESSAGES,
    AutoMod,
)
from aestron_bot.calls import CallInviteView, Calls
from aestron_bot.fun import FunGames
from aestron_bot.giveaways import Giveaways, GiveawayView
from aestron_bot.leveling import Leveling
from aestron_bot.moderation import Moderation
from aestron_bot.profiles import build_profile_embed
from aestron_bot.templates import Templates, _template_code
from aestron_bot.tickets import (
    OpenTicketView,
    TicketControls,
    Tickets,
    _safe_channel_name,
)
from aestron_bot.verification import Captcha, VerificationView


def test_production_uses_modern_safety_cogs():
    """Production must register each maintained modular cog exactly once."""
    cog_types = main.get_cog_types()
    assert AntiRaid in cog_types
    assert AuditLogging in cog_types
    assert Tickets in cog_types
    assert Templates in cog_types
    assert Captcha in cog_types
    assert AutoMod in cog_types
    assert Giveaways in cog_types
    assert Leveling in cog_types
    assert Calls in cog_types
    assert len(cog_types) == len(set(cog_types))
    for cog in (
        AntiRaid,
        AuditLogging,
        AutoMod,
        Tickets,
        Templates,
        Captcha,
        Giveaways,
        Leveling,
        Calls,
    ):
        assert cog.__module__.startswith("aestron_bot.")


def test_antiraid_covers_destructive_actions_and_permissions():
    """The enforcement window must include common raid primitives."""
    assert {
        discord.AuditLogAction.channel_delete,
        discord.AuditLogAction.role_delete,
        discord.AuditLogAction.ban,
        discord.AuditLogAction.kick,
        discord.AuditLogAction.webhook_create,
    } <= DANGEROUS_ACTIONS
    assert AntiRaid._dangerous_role(
        SimpleNamespace(permissions=SimpleNamespace(administrator=True))
    )
    assert not AntiRaid._dangerous_role(
        SimpleNamespace(
            permissions=SimpleNamespace(
                administrator=False,
                manage_guild=False,
                manage_channels=False,
                manage_roles=False,
                manage_webhooks=False,
                ban_members=False,
                kick_members=False,
            )
        )
    )


def test_template_and_antiraid_mutations_have_runtime_guards():
    """High-impact slash actions require checks in addition to UI defaults."""
    template_checks = {
        command.name: len(command.checks) for command in Templates.template.commands
    }
    assert template_checks == {
        "backup": 2,
        "list": 1,
        "preview": 1,
        "sync": 2,
        "delete": 2,
    }
    assert all(len(command.checks) == 2 for command in AntiRaid.antiraid.commands)
    assert Templates.backuptemplate._buckets.valid


def test_profile_builder_avoids_expensive_server_wide_scans():
    """Profiles must use bounded Discord data instead of enumerating bans."""
    source = inspect.getsource(build_profile_embed)
    assert ".bans(" not in source
    assert "uservoted" not in source


def test_safety_slash_groups_are_compact_and_complete():
    """Grouped commands preserve Discord's global root-command budget."""
    assert {command.name for command in AntiRaid.antiraid.commands} == {
        "enable",
        "disable",
        "status",
        "configure",
    }
    assert {command.name for command in AuditLogging.logs.commands} == {
        "setup",
        "disable",
        "overview",
    }
    assert {command.name for command in Tickets.ticket.commands} == {
        "setup",
        "claim",
        "lock",
        "transcript",
        "close",
        "add",
        "remove",
    }
    assert {command.name for command in AutoMod.automod.commands} == {
        "set",
        "status",
    }
    assert {command.name for command in Leveling.leveling.commands} == {
        "rank",
        "leaderboard",
        "configure",
    }


def test_automod_has_native_link_and_spam_enforcement():
    """Modern AutoMod must detect links and use a bounded spam window."""
    assert LINK_PATTERN.search("visit https://example.com/path")
    assert LINK_PATTERN.search("discord.gg/example")
    cog = AutoMod(SimpleNamespace())
    message = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        channel=SimpleNamespace(id=2),
        author=SimpleNamespace(id=3),
    )
    for _ in range(SPAM_MESSAGES - 1):
        assert not cog._is_spam(message)
    assert cog._is_spam(message)


def test_fun_leveling_and_minecraft_regressions_are_registered():
    """Reviewed gameplay areas keep their commands, limits, and safe timing."""
    fun_commands = {command.name for command in FunGames.__cog_commands__}
    assert {"coinflip", "roll", "choose", "eightball", "rate", "rps", "trivia"} <= (
        fun_commands
    )
    assert main.MinecraftFun.voterewardweekly._buckets._cooldown.per == 604800
    assert main.MinecraftFun.votereward._buckets._cooldown.per == 86400
    daily_source = inspect.getsource(main.MinecraftFun.votereward.callback)
    payment_source = inspect.getsource(main.MinecraftFun.payment.callback)
    pvp_source = inspect.getsource(main.MinecraftFun.pvp.callback)
    assert "await uservoted" in daily_source
    assert "FOR UPDATE" in payment_source
    assert "con.transaction()" in payment_source
    assert "MinecraftVoiceEffects.connect" in pvp_source
    assert "voice_channel: discord.VoiceChannel | None" in pvp_source
    view = main.Minecraftpvp(1, 2, "one", "two", 20, 20, 10, 10, 5, 5, None)
    assert view.timeout == 300


def test_ticket_views_are_persistent_and_channel_names_are_safe():
    """Restart-safe controls require stable custom IDs and no view timeout."""
    open_view = OpenTicketView()
    controls = TicketControls()
    assert open_view.timeout is None
    assert controls.timeout is None
    custom_ids = {item.custom_id for item in open_view.children + controls.children}
    assert custom_ids == {
        "aestron:ticket:open:v1",
        "aestron:ticket:claim:v1",
        "aestron:ticket:lock:v1",
        "aestron:ticket:transcript:v1",
        "aestron:ticket:close:v1",
    }
    assert _safe_channel_name(" JPR Coder!! ") == "jpr-coder"
    assert _safe_channel_name("✨") == "member"


def test_verification_button_is_restart_safe_and_template_urls_are_validated():
    """Verification survives restarts and templates accept only Discord URLs."""
    view = VerificationView()
    assert view.timeout is None
    assert [item.custom_id for item in view.children] == ["verification:green"]
    assert _template_code("https://discord.new/AbC-123") == "AbC-123"


def test_giveaway_buttons_are_restart_safe():
    """Giveaway entry controls must survive bot process restarts."""
    view = GiveawayView()
    assert view.timeout is None
    assert {item.custom_id for item in view.children} == {
        "aestron:giveaway:enter:v1",
        "aestron:giveaway:leave:v1",
    }


def test_private_call_invites_are_bounded_and_consent_based():
    """Call prompts expire and expose only explicit answer controls."""
    view = CallInviteView(receiver_id=123)
    assert view.timeout == 60
    assert {item.label for item in view.children} == {"Accept", "Decline"}
    assert {command.name for command in Calls.calls.commands} == {
        "privacy",
        "status",
        "hangup",
    }


def test_high_impact_moderation_commands_have_cooldowns():
    """Destructive commands must be throttled independently of global spam control."""
    for name in (
        "lock",
        "unlock",
        "setslowmode",
        "purge",
        "selfpurge",
        "warn",
        "clearwarnings",
        "ban",
        "unban",
        "kick",
        "timeout",
        "untimeout",
        "softban",
    ):
        assert getattr(Moderation, name)._buckets.valid, name
