"""Regression tests for moderation, anti-raid, logging, and tickets."""

import asyncio
import inspect
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from PIL import Image

import main
from aestron_bot.antiraid import DANGEROUS_ACTIONS, AntiRaid
from aestron_bot.audit_logging import AuditLogging
from aestron_bot.automod import (
    LINK_PATTERN,
    SPAM_MESSAGES,
    AutoMod,
)
from aestron_bot.calls import CallInviteView, Calls
from aestron_bot.fun import (
    TRIVIA_QUESTIONS,
    FunGames,
    RockPaperScissorsView,
    TriviaView,
    WouldYouRatherView,
)
from aestron_bot.giveaways import Giveaways, GiveawayView
from aestron_bot.leveling import Leveling
from aestron_bot.moderation import Moderation
from aestron_bot.profiles import build_profile_embed
from aestron_bot.social import _render_wanted, _render_welcome
from aestron_bot.templates import Templates, _template_code
from aestron_bot.tickets import (
    OpenTicketView,
    TicketControls,
    Tickets,
    _safe_channel_name,
)
from aestron_bot.valorant import Valorant
from aestron_bot.verification import Captcha, VerificationView


def test_production_uses_maintained_safety_cogs():
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


def test_unfiltered_purge_omits_none_check_callback():
    """discord.py must receive no check keyword when purging every author."""

    async def run_test():
        bot = SimpleNamespace(get_cog=lambda _name: None)
        moderation = Moderation(bot)
        channel = SimpleNamespace(
            purge=AsyncMock(return_value=[object(), object()]),
            mention="#general",
        )
        ctx = SimpleNamespace(
            author=SimpleNamespace(id=42, __str__=lambda self: "Moderator"),
            channel=channel,
            guild=SimpleNamespace(id=99),
            send=AsyncMock(),
        )

        await Moderation.purge.callback(
            moderation,
            ctx,
            25,
            None,
            reason="cleanup",
        )

        options = channel.purge.await_args.kwargs
        assert options["limit"] == 25
        assert "check" not in options
        ctx.send.assert_awaited_once()

    asyncio.run(run_test())


def test_legacy_custom_command_names_are_normalized_once(monkeypatch, caplog):
    """Mixed-case database rows must not emit startup warnings forever."""

    class AsyncContext:
        def __init__(self, value):
            self.value = value

        async def __aenter__(self):
            return self.value

        async def __aexit__(self, *_args):
            return False

    class Connection:
        def __init__(self):
            self.executions = []

        def transaction(self):
            return AsyncContext(self)

        async def fetch(self, *_args):
            return [{"guildid": 9, "commandname": "Hi"}]

        async def fetchval(self, *_args):
            return False

        async def execute(self, query, *args):
            self.executions.append((query, args))

    async def run_test():
        connection = Connection()
        pool = SimpleNamespace(acquire=lambda: AsyncContext(connection))
        monkeypatch.setattr(main.client, "database", SimpleNamespace(pool=pool))

        bot = SimpleNamespace(
            wait_until_ready=AsyncMock(),
            get_command=lambda _name: SimpleNamespace(extras={}),
        )
        custom_commands = main.CustomCommands(bot)
        with caplog.at_level("WARNING", logger="aestron"):
            await custom_commands._load_custom_commands()

        assert connection.executions
        query, args = connection.executions[0]
        assert "UPDATE customcommands SET commandname" in query
        assert args == ("hi", 9, "Hi")
        assert not caplog.records

    asyncio.run(run_test())


def test_social_cards_render_at_shareable_resolution():
    """Generated welcome and bounty assets should not depend on legacy backgrounds."""
    source = BytesIO()
    Image.new("RGB", (512, 512), (70, 120, 210)).save(source, format="PNG")
    avatar = source.getvalue()

    welcome = _render_welcome(avatar, "Builder", 128, "Block Party", "aurora")
    wanted, bounty = _render_wanted(
        avatar, "Griefer", "borrowed the diamonds", "chaos", 42
    )

    with Image.open(BytesIO(welcome)) as image:
        assert image.size == (1200, 480)
    with Image.open(BytesIO(wanted)) as image:
        assert image.size == (1200, 480)
    assert 10_000 <= bounty < 12_500


def test_fun_sessions_expose_scored_and_public_controls():
    """Core fun games should retain meaningful multi-step session state."""
    rps = RockPaperScissorsView(1)
    trivia = TriviaView(1, TRIVIA_QUESTIONS[0])
    poll = WouldYouRatherView(1)

    assert (rps.player_score, rps.bot_score, rps.round) == (0, 0, 0)
    assert len(rps.children) == 3
    assert trivia.round_number == 1 and trivia.score == 0
    assert len(trivia.children) == 4
    assert len(poll.children) == 3


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
    assert {command.name for command in Valorant.valorant.commands} == {
        "link",
        "unlink",
        "stats",
        "history",
        "match",
        "coach",
    }


def test_automod_has_native_link_and_spam_enforcement():
    """AutoMod must detect links and use a bounded spam window."""
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
    reward_source = inspect.getsource(main.MinecraftFun._claim_reward)
    payment_source = inspect.getsource(main.MinecraftFun.payment.callback)
    pvp_source = inspect.getsource(main.MinecraftFun.pvp.callback)
    assert "minecraft_reward_claims" in reward_source
    assert "con.transaction()" in reward_source
    assert "await uservoted" in reward_source
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


def test_template_backup_refreshes_discords_single_existing_template():
    """Backup must sync and edit the existing template instead of creating a second."""

    async def run_test():
        updated = SimpleNamespace()
        synced = SimpleNamespace(edit=AsyncMock(return_value=updated))
        existing = SimpleNamespace(sync=AsyncMock(return_value=synced))
        guild = SimpleNamespace(
            name="Example Guild",
            templates=AsyncMock(return_value=[existing]),
            create_template=AsyncMock(),
        )
        cog = Templates(SimpleNamespace())

        result = await cog._create_backup(guild, "Current server state")

        assert result is updated
        existing.sync.assert_awaited_once_with()
        synced.edit.assert_awaited_once_with(
            name="Example Guild backup",
            description="Current server state",
        )
        guild.create_template.assert_not_awaited()

    asyncio.run(run_test())


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
