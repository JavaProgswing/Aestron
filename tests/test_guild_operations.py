"""Regression coverage for fleet activity and consent-based broadcasts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aestron_bot.guild_operations import GuildOperations
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
    }
    assert all(command.checks for command in GuildOperations.botadmin.commands)


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
