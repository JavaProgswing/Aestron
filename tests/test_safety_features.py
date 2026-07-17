"""Regression tests for moderation, anti-raid, logging, and tickets."""

import asyncio
import inspect
from datetime import timedelta
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
    AutoModChannelSelect,
    AutoModPolicy,
    AutoModSetupView,
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
from aestron_bot.onboarding import ServerGuideView, ServerOnboarding
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
from aestron_bot.verification import Captcha, VerificationSetupView, VerificationView


def test_production_uses_maintained_safety_cogs():
    """Production must register each maintained modular cog exactly once."""
    cog_types = main.get_cog_types()
    assert AntiRaid in cog_types
    assert AuditLogging in cog_types
    assert Tickets in cog_types
    assert Templates in cog_types
    assert Captcha in cog_types
    assert AutoMod in cog_types
    assert ServerOnboarding in cog_types
    assert Giveaways in cog_types
    assert Leveling in cog_types
    assert Calls in cog_types
    assert len(cog_types) == len(set(cog_types))
    for cog in (
        AntiRaid,
        AuditLogging,
        AutoMod,
        ServerOnboarding,
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


def test_antiraid_enable_uses_canonical_transactional_settings():
    """Old anti-raid tables must not be used as an upsert conflict target."""

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
            self.transactions = 0

        def transaction(self):
            self.transactions += 1
            return AsyncContext(self)

        async def execute(self, query, *args):
            self.executions.append((" ".join(query.split()), args))

    async def run_test():
        connection = Connection()
        pool = SimpleNamespace(acquire=lambda: AsyncContext(connection))
        cog = AntiRaid(SimpleNamespace(database=SimpleNamespace(pool=pool)))
        guild = SimpleNamespace(id=91, me=object())
        permissions = SimpleNamespace(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            view_audit_log=True,
        )
        channel = SimpleNamespace(
            id=37,
            guild=guild,
            permissions_for=lambda _member: permissions,
        )

        await cog._enable(guild, channel)

        assert connection.transactions == 1
        assert len(connection.executions) == 2
        settings_query, settings_args = connection.executions[0]
        cleanup_query, cleanup_args = connection.executions[1]
        assert "INSERT INTO antiraid_settings" in settings_query
        assert "ON CONFLICT (guild_id) DO UPDATE" in settings_query
        assert settings_args == (91, 37)
        assert cleanup_query == "DELETE FROM antiraid WHERE guildid = $1"
        assert cleanup_args == (91,)
        assert all(
            "ON CONFLICT (guildid)" not in query
            for query, _args in connection.executions
        )

    asyncio.run(run_test())


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
        "setup",
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
    custom = AutoModPolicy(spam_messages=3, spam_window_seconds=30)
    for _ in range(2):
        assert not cog._is_spam(message, custom)
    assert cog._is_spam(message, custom)


def test_fun_leveling_and_minecraft_regressions_are_registered():
    """Reviewed gameplay areas keep their commands, limits, and safe timing."""
    fun_commands = {command.name for command in FunGames.__cog_commands__}
    assert {"coinflip", "roll", "choose", "eightball", "rate", "rps", "trivia"} <= (
        fun_commands
    )
    reward_source = inspect.getsource(main.MinecraftFun._claim_reward)
    setup_source = inspect.getsource(main.MinecraftFun.cog_load)
    payment_source = inspect.getsource(main.MinecraftFun.payment.callback)
    pvp_source = inspect.getsource(main.MinecraftFun.pvp.callback)
    assert "minecraft_reward_claims" in reward_source
    assert "ALTER TABLE leaderboard ADD COLUMN IF NOT EXISTS wins" in setup_source
    assert "con.transaction()" in reward_source
    assert "await uservoted" in reward_source
    assert "FOR UPDATE" in payment_source
    assert "con.transaction()" in payment_source
    assert "MinecraftVoiceEffects.connect" in pvp_source
    assert "voice_channel: discord.VoiceChannel | None" in pvp_source
    assert pvp_source.index("await ctx.defer") < pvp_source.index("asyncio.gather")
    view = main.Minecraftpvp(
        memberone_id=1,
        membertwo_id=2,
        memberone_name="one",
        membertwo_name="two",
        memberone_health=20,
        membertwo_health=20,
        memberone_armor="Leather",
        membertwo_armor="Leather",
        memberone_sword="Wooden",
        membertwo_sword="Wooden",
        memberone_avatar=b"",
        membertwo_avatar=b"",
        voice_effects=None,
    )
    assert view.timeout == 300
    assert {item.label for item in view.children} == {
        "Yield",
        "Guard",
        "Golden apple",
        "Strike",
    }
    assert len(view.render_board()) > 10_000
    attack_source = inspect.getsource(main.Minecraftpvp.attack)
    assert attack_source.index("await interaction.response.defer") < (
        attack_source.index("await self._refresh_message")
    )
    assert main.Minecraftpvp._refresh is discord.ui.View._refresh
    award_source = inspect.getsource(main.Minecraftpvp._award)
    assert "ON CONFLICT (mention) DO UPDATE" in award_source
    assert "wins = leaderboard.wins + 1" in award_source


def test_minecraft_golden_apple_is_not_wasted_at_full_health():
    """A full-health fighter keeps their single-use heal and their turn."""

    async def run_test():
        view = main.Minecraftpvp(
            memberone_id=1,
            membertwo_id=2,
            memberone_name="one",
            membertwo_name="two",
            memberone_health=20,
            membertwo_health=20,
            memberone_armor="Leather",
            membertwo_armor="Leather",
            memberone_sword="Wooden",
            membertwo_sword="Wooden",
            memberone_avatar=b"",
            membertwo_avatar=b"",
            voice_effects=None,
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=1),
            response=SimpleNamespace(
                send_message=AsyncMock(),
                defer=AsyncMock(),
            ),
        )
        heal_button = next(
            item for item in view.children if item.custom_id == "minecraftpvp:heal"
        )

        await heal_button.callback(interaction)

        interaction.response.send_message.assert_awaited_once()
        interaction.response.defer.assert_not_awaited()
        assert view.memberone_heal_available is True
        assert view.memberone_healthpoint == 20
        assert view.moveturn == 1

    asyncio.run(run_test())


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


def test_ticket_claim_button_does_not_overwrite_or_repeat_claims():
    """Persistent claim clicks must report existing ownership truthfully."""

    class AsyncContext:
        async def __aenter__(self):
            return connection

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class Connection:
        def __init__(self):
            self.claim_updates = 0

        async def fetchval(self, query, *args):
            assert "claimed_by IS NULL" in query
            self.claim_updates += 1
            return args[0]

    async def run_test():
        nonlocal connection
        connection = Connection()
        pool = SimpleNamespace(acquire=AsyncContext)
        bot = SimpleNamespace(database=SimpleNamespace(pool=pool))
        cog = Tickets(bot)
        cog._require_ticket_access = AsyncMock(
            side_effect=[
                {"claimed_by": None},
                {"claimed_by": 55},
                {"claimed_by": 99},
            ]
        )
        cog._log_event = AsyncMock()

        def interaction():
            return SimpleNamespace(
                user=SimpleNamespace(id=55, mention="<@55>"),
                channel_id=456,
                channel=SimpleNamespace(id=456),
                guild=SimpleNamespace(id=123),
                response=SimpleNamespace(send_message=AsyncMock()),
            )

        first = interaction()
        await cog.claim_ticket(first)
        assert "claimed by <@55>" in first.response.send_message.await_args.args[0]

        duplicate = interaction()
        await cog.claim_ticket(duplicate)
        assert "already claimed" in duplicate.response.send_message.await_args.args[0]

        occupied = interaction()
        await cog.claim_ticket(occupied)
        assert "already claimed by <@99>" in (
            occupied.response.send_message.await_args.args[0]
        )
        assert connection.claim_updates == 1
        cog._log_event.assert_awaited_once()

    connection = None
    asyncio.run(run_test())


def test_guided_safety_setup_is_multi_channel_and_restart_safe():
    """Guides cover multiple channel types while public buttons survive restarts."""
    automod_source = inspect.getsource(AutoModSetupView)
    verification_source = inspect.getsource(VerificationSetupView)
    assert "max_values=25" in inspect.getsource(AutoModChannelSelect)
    assert "configure_channels" in automod_source
    assert "Use all public" in verification_source
    setup_source = inspect.getsource(Captcha._setup)
    assert "onboarding_default_ids" in setup_source
    assert setup_source.index('reason="Aestron verified access"') < setup_source.index(
        'reason="Aestron verification public-channel lock"'
    )
    guide = ServerGuideView()
    assert guide.timeout is None
    assert {item.custom_id for item in guide.children} == {
        "aestron:guide:automod:v1",
        "aestron:guide:verification:v1",
        "aestron:guide:tickets:v1",
        "aestron:guide:overview:v1",
    }


def test_verification_button_is_restart_safe_and_template_urls_are_validated():
    """Verification survives restarts and templates accept only Discord URLs."""
    view = VerificationView()
    assert view.timeout is None
    assert [item.custom_id for item in view.children] == ["verification:green"]
    assert _template_code("https://discord.new/AbC-123") == "AbC-123"


def test_template_backup_refreshes_discords_single_existing_template():
    """Backup must bypass discord.py's fragile source-guild deserialization."""

    async def run_test():
        payload = {
            "code": "backup-code",
            "name": "Example Guild backup",
            "description": "Current server state",
            "usage_count": 2,
            "source_guild_id": "123",
            "serialized_source_guild": {
                "name": "Example Guild",
                "channels": [{"id": "1"}],
                # This nullable value is what crashes discord.Template in 2.7.1.
                "roles": [{"id": "1", "colors": None}],
            },
        }
        http = SimpleNamespace(
            guild_templates=AsyncMock(return_value=[payload]),
            sync_template=AsyncMock(return_value=payload),
            edit_template=AsyncMock(return_value=payload),
            create_template=AsyncMock(),
        )
        guild = SimpleNamespace(
            id=123,
            name="Example Guild",
            _state=SimpleNamespace(http=http),
        )
        cog = Templates(SimpleNamespace())

        result = await cog._create_backup(guild, "Current server state")

        assert result.code == "backup-code"
        assert result.role_count == 1
        http.sync_template.assert_awaited_once_with(123, "backup-code")
        http.edit_template.assert_awaited_once_with(
            123,
            "backup-code",
            {
                "name": "Example Guild backup",
                "description": "Current server state",
            },
        )
        http.create_template.assert_not_awaited()

    asyncio.run(run_test())


def test_giveaway_buttons_are_restart_safe():
    """Giveaway entry controls must survive bot process restarts."""
    view = GiveawayView()
    assert view.timeout is None
    assert {item.custom_id for item in view.children} == {
        "aestron:giveaway:enter:v1",
        "aestron:giveaway:leave:v1",
    }


def test_giveaway_entry_buttons_report_real_changes_and_refresh_count():
    """Duplicate entry/leave clicks must not claim a database change occurred."""

    class AsyncContext:
        def __init__(self, value=None):
            self.value = value

        async def __aenter__(self):
            return self.value

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class GiveawayConnection:
        def __init__(self):
            self.entries: set[int] = set()
            self.row = {
                "message_id": 987,
                "guild_id": 123,
                "channel_id": 456,
                "host_id": 42,
                "prize": "A useful prize",
                "winner_count": 1,
                "ends_at": discord.utils.utcnow() + timedelta(hours=1),
                "status": "active",
            }

        def transaction(self):
            return AsyncContext()

        async def fetchrow(self, query, message_id):
            assert "FOR UPDATE" in query
            assert message_id == self.row["message_id"]
            return self.row

        async def fetchval(self, query, message_id, user_id=None):
            assert message_id == self.row["message_id"]
            if query.startswith("INSERT"):
                if user_id in self.entries:
                    return None
                self.entries.add(user_id)
                return user_id
            if query.startswith("DELETE"):
                if user_id not in self.entries:
                    return None
                self.entries.remove(user_id)
                return user_id
            assert "COUNT(*)" in query
            return len(self.entries)

    async def run_test():
        connection = GiveawayConnection()
        pool = SimpleNamespace(acquire=lambda: AsyncContext(connection))
        bot = SimpleNamespace(database=SimpleNamespace(pool=pool))
        cog = Giveaways(bot)
        message = SimpleNamespace(id=987, edit=AsyncMock())

        def interaction():
            return SimpleNamespace(
                message=message,
                guild=SimpleNamespace(id=123),
                user=SimpleNamespace(id=55),
                response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()),
            )

        entered = interaction()
        await cog.update_entry(entered, enter=True)
        assert "You entered" in entered.followup.send.await_args.args[0]
        assert "Entries: 1" in entered.followup.send.await_args.args[0]

        duplicate = interaction()
        await cog.update_entry(duplicate, enter=True)
        assert "already entered" in duplicate.followup.send.await_args.args[0]
        assert len(connection.entries) == 1

        left = interaction()
        await cog.update_entry(left, enter=False)
        assert "You left" in left.followup.send.await_args.args[0]
        assert "Entries: 0" in left.followup.send.await_args.args[0]

        missing = interaction()
        await cog.update_entry(missing, enter=False)
        assert "were not entered" in missing.followup.send.await_args.args[0]
        assert len(connection.entries) == 0

        latest_embed = message.edit.await_args.kwargs["embed"]
        entries_field = next(
            field for field in latest_embed.fields if field.name == "Entries"
        )
        assert entries_field.value == "0"
        assert message.edit.await_count == 4

    asyncio.run(run_test())


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
