"""Regression coverage for fleet activity and consent-based broadcasts."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from aestron_bot.guild_operations import GuildOperations, scope_operations_commands
from aestron_bot.guild_pruning import PruneCandidate
from aestron_bot.update_broadcasts import BroadcastDraft


class AsyncContext:
    """Minimal asynchronous context manager used by fake pools."""

    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return False


def test_guild_operations_groups_are_bounded_and_owner_checked():
    assert {command.name for command in GuildOperations.updates.commands} == {
        "subscribe",
        "unsubscribe",
        "status",
    }
    assert {command.name for command in GuildOperations.botadmin.commands} == {
        "activity",
        "broadcast",
        "broadcasts",
        "prune",
    }
    assert all(command.checks for command in GuildOperations.botadmin.commands)


def test_operation_groups_move_to_one_configured_guild():
    client = discord.Client(intents=discord.Intents.none())
    tree = discord.app_commands.CommandTree(client)
    tree.add_command(discord.app_commands.Group(name="updates", description="Updates"))
    tree.add_command(
        discord.app_commands.Group(name="botadmin", description="Administration")
    )

    guild = scope_operations_commands(tree, 123)

    assert guild is not None and guild.id == 123
    assert tree.get_command("updates") is None
    assert tree.get_command("botadmin") is None
    assert tree.get_command("updates", guild=guild) is not None
    assert tree.get_command("botadmin", guild=guild) is not None


def test_activity_is_batched_without_message_content_or_author_data():
    class Connection:
        def __init__(self):
            self.rows = []

        async def executemany(self, query, rows):
            assert "aestron_guild_activity" in query
            assert "$4::TIMESTAMPTZ" in query
            assert "$5::TIMESTAMPTZ" in query
            assert "GREATEST($4::TIMESTAMPTZ, $5::TIMESTAMPTZ)" in query
            self.rows.extend(rows)

    async def run_test():
        connection = Connection()
        bot = SimpleNamespace(
            database=SimpleNamespace(
                connected=True,
                pool=SimpleNamespace(acquire=lambda: AsyncContext(connection)),
            )
        )
        cog = GuildOperations(bot)
        cog.activity.record(91, command=False)
        cog.activity.record(91, command=False)
        cog.activity.record(91, command=True)

        await cog.activity.flush()

        assert len(connection.rows) == 1
        guild_id, messages, commands, last_message, last_command = connection.rows[0]
        assert (guild_id, messages, commands) == (91, 2, 1)
        assert last_message is not None and last_command is not None
        assert cog.activity.pending == {}

    asyncio.run(run_test())


def test_failed_activity_flush_is_retried_without_losing_new_events():
    """A failed batch must merge back with events recorded before its retry."""

    class Connection:
        def __init__(self):
            self.fail = True
            self.rows = []

        async def executemany(self, _query, rows):
            if self.fail:
                raise RuntimeError("temporary database failure")
            self.rows.extend(rows)

    async def run_test():
        connection = Connection()
        bot = SimpleNamespace(
            database=SimpleNamespace(
                connected=True,
                pool=SimpleNamespace(acquire=lambda: AsyncContext(connection)),
            )
        )
        cog = GuildOperations(bot)
        cog.activity.record(91, command=False)

        await cog.activity.flush()
        assert cog.activity.pending[91].messages == 1

        cog.activity.record(91, command=True)
        connection.fail = False
        await cog.activity.flush()

        assert len(connection.rows) == 1
        guild_id, messages, commands, last_message, last_command = connection.rows[0]
        assert (guild_id, messages, commands) == (91, 1, 1)
        assert last_message is not None and last_command is not None
        assert cog.activity.pending == {}

    asyncio.run(run_test())


def test_guild_observation_seeding_does_not_invent_activity():
    """Current guilds get observation rows with zero synthetic messages."""

    class Connection:
        def __init__(self):
            self.query = ""
            self.rows = []
            self.reset_query = ""
            self.reset_guild_id = None

        async def executemany(self, query, rows):
            self.query = query
            self.rows.extend(rows)

        async def execute(self, query, guild_id):
            self.reset_query = query
            self.reset_guild_id = guild_id

    async def run_test():
        connection = Connection()
        bot = SimpleNamespace(
            database=SimpleNamespace(
                connected=True,
                pool=SimpleNamespace(acquire=lambda: AsyncContext(connection)),
            )
        )
        cog = GuildOperations(bot)

        await cog.activity.seed_guilds([91, 92, 91])

        assert connection.rows == [(91,), (92,)]
        assert "ON CONFLICT (guild_id) DO NOTHING" in connection.query
        assert "message_count" not in connection.query

        await cog.activity.reset_joined_guild(91)
        assert connection.reset_guild_id == 91
        assert "first_seen_at = NOW()" in connection.reset_query
        assert "last_active_at = NULL" in connection.reset_query

    asyncio.run(run_test())


def test_prune_revalidates_activity_and_protects_the_control_guild():
    """Cleanup leaves only still-inactive guilds from the confirmed snapshot."""

    class Connection:
        async def fetch(self, _query, _guild_ids):
            now = discord.utils.utcnow()
            return [
                {
                    "guild_id": 91,
                    "first_seen_at": now - timedelta(days=60),
                    "last_active_at": now - timedelta(days=45),
                },
                {
                    "guild_id": 92,
                    "first_seen_at": now - timedelta(days=60),
                    "last_active_at": now - timedelta(minutes=1),
                },
                {
                    "guild_id": 93,
                    "first_seen_at": now - timedelta(days=60),
                    "last_active_at": now - timedelta(days=45),
                },
            ]

    async def run_test():
        connection = Connection()
        guilds = {
            guild_id: SimpleNamespace(
                id=guild_id,
                name=f"Guild {guild_id}",
                leave=AsyncMock(),
            )
            for guild_id in (91, 92, 93)
        }
        bot = SimpleNamespace(
            database=SimpleNamespace(
                pool=SimpleNamespace(acquire=lambda: AsyncContext(connection))
            ),
            get_guild=lambda guild_id: guilds.get(guild_id),
        )
        cog = GuildOperations(bot)
        cog.pruning._send_notice = AsyncMock(return_value="not_requested")
        old = discord.utils.utcnow() - timedelta(days=60)
        candidates = [
            PruneCandidate(guild_id, f"Guild {guild_id}", 10, old, old)
            for guild_id in (91, 92, 93)
        ]

        results = await cog.pruning.execute(
            candidates,
            inactive_for=timedelta(days=30),
            protected_guild_id=93,
            farewell_message=None,
            invite_url=None,
        )

        guilds[91].leave.assert_awaited_once()
        guilds[92].leave.assert_not_awaited()
        guilds[93].leave.assert_not_awaited()
        assert [(result.guild_id, result.outcome) for result in results] == [
            (91, "left"),
            (92, "skipped"),
            (93, "skipped"),
        ]

    asyncio.run(run_test())


def test_broadcast_never_scans_for_a_fallback_channel():
    class Connection:
        def __init__(self):
            self.delivery_rows = []

        async def fetch(self, query, *_args):
            if "guild_update_subscriptions" in query:
                return [{"guild_id": 91, "channel_id": 404}]
            return []

        async def fetchval(self, *_args):
            return 7

        async def executemany(self, query, rows):
            assert "bot_broadcast_deliveries" in query
            self.delivery_rows.extend(rows)

    async def run_test():
        connection = Connection()
        fallback = SimpleNamespace(send=AsyncMock())
        guild = SimpleNamespace(
            id=91,
            get_channel=lambda _channel_id: None,
            text_channels=[fallback],
        )
        bot = SimpleNamespace(
            database=SimpleNamespace(
                pool=SimpleNamespace(acquire=lambda: AsyncContext(connection))
            ),
            get_guild=lambda guild_id: guild if guild_id == 91 else None,
        )
        cog = GuildOperations(bot)
        result = await cog.broadcasts.broadcast(
            BroadcastDraft(
                title="Update",
                summary="A safe update.",
                details=None,
                status="operational",
                include_stats=False,
                created_by=1,
            )
        )

        fallback.send.assert_not_awaited()
        assert connection.delivery_rows == [(7, 91, 404, "unavailable", "missing")]
        assert result.fields[0].value == "0"
        assert result.fields[1].value == "1"

    asyncio.run(run_test())
