import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import wavelink

from aestron_bot.lavalink import LavalinkService
from aestron_bot.music import Music, QueueView, _format_duration


class FakeQueue:
    def __init__(self):
        self.tracks = []

    async def put_wait(self, track):
        self.tracks.append(track)
        return 1

    def get(self):
        return self.tracks.pop(0)

    def put_at(self, index, track):
        self.tracks.insert(index, track)

    def __iter__(self):
        return iter(self.tracks)

    @property
    def count(self):
        return len(self.tracks)


def test_play_searches_queues_and_starts_track(monkeypatch):
    async def run_test():
        bot = SimpleNamespace(
            lavalink=SimpleNamespace(
                search_source="ytsearch",
                node=object(),
            )
        )
        cog = Music(bot)
        track = SimpleNamespace(
            title="Test Track",
            uri="https://example.com/track",
            extras=None,
            identifier="test-track",
            author="Test Artist",
            source="youtube",
            length=180_000,
            artwork="https://example.com/artwork.jpg",
        )
        search = AsyncMock(return_value=[track])
        monkeypatch.setattr(wavelink.Playable, "search", search)

        player = SimpleNamespace(
            queue=FakeQueue(),
            playing=False,
            current=None,
            play=AsyncMock(),
            guild=SimpleNamespace(id=123),
            volume=75,
        )
        cog._get_player = AsyncMock(return_value=player)
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            author=SimpleNamespace(id=456, display_name="Requester"),
            channel=SimpleNamespace(id=789),
            command=SimpleNamespace(reset_cooldown=lambda _: None),
            send=AsyncMock(),
        )

        await Music.play.callback(cog, ctx, query="test song")

        search.assert_awaited_once_with(
            "test song", source="ytsearch", node=bot.lavalink.node
        )
        player.play.assert_awaited_once_with(track)
        assert track.extras == {"requester_id": 456, "text_channel_id": 789}
        ctx.send.assert_awaited_once()
        sent_embed = ctx.send.await_args.kwargs["embed"]
        assert sent_embed.title == "Now playing 🎶"
        assert "Test Track" in sent_embed.description
        assert ctx.send.await_args.kwargs["view"] is not None

    asyncio.run(run_test())


def test_music_commands_have_clear_usage_metadata():
    expected = {
        "play",
        "skip",
        "currentlyplaying",
        "queue",
        "pause",
        "stop",
        "volume",
        "voicehealth",
    }
    commands = {command.name: command for command in Music.__cog_commands__}
    assert expected <= commands.keys()
    for command_name in expected:
        command = commands[command_name]
        assert command.brief
        assert command.description
        assert command.usage is not None


def test_queue_view_paginates_every_track_with_stable_numbers():
    async def run_test():
        queue = FakeQueue()
        queue.tracks.extend(
            SimpleNamespace(title=f"Track {index}", uri=f"https://example.com/{index}")
            for index in range(1, 24)
        )
        current = SimpleNamespace(
            title="Current Track", uri="https://example.com/current"
        )
        view = QueueView(SimpleNamespace(current=current, queue=queue), author_id=123)

        assert view.page_count == 3
        assert "Track 1" in view.render().description
        assert "Track 11" not in view.render().description

        view.page = 1
        second_page = view.render()
        assert "**11.**" in second_page.description
        assert "Track 11" in second_page.description
        assert second_page.footer.text == "Page 2/3 • 23 track(s) waiting"

    asyncio.run(run_test())


def test_music_duration_drops_fractional_seconds():
    assert _format_duration(75_200) == "0:01:15"


def test_play_restores_track_and_reports_lavalink_playback_failure(monkeypatch):
    async def run_test():
        bot = SimpleNamespace(
            lavalink=SimpleNamespace(search_source="ytsearch", node=object())
        )
        cog = Music(bot)
        track = SimpleNamespace(
            title="Broken Track",
            uri="https://example.com/broken",
            extras=None,
            identifier="broken-track",
        )
        monkeypatch.setattr(
            wavelink.Playable, "search", AsyncMock(return_value=[track])
        )
        player = SimpleNamespace(
            queue=FakeQueue(),
            playing=False,
            current=None,
            play=AsyncMock(side_effect=wavelink.WavelinkException("rejected")),
        )
        cog._get_player = AsyncMock(return_value=player)
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            author=SimpleNamespace(id=456, display_name="Requester"),
            channel=SimpleNamespace(id=789),
            command=SimpleNamespace(reset_cooldown=lambda _: None),
            send=AsyncMock(),
        )

        await Music.play.callback(cog, ctx, query="broken song")

        assert player.queue.tracks == [track]
        sent_embed = ctx.send.await_args.kwargs["embed"]
        assert sent_embed.title == "Music error"
        assert "could not start playback" in sent_embed.description

    asyncio.run(run_test())


def test_lavalink_search_probe_requires_an_encoded_track(monkeypatch):
    async def run_test():
        service = LavalinkService(SimpleNamespace())
        service.ensure_connected = AsyncMock(return_value=True)
        track = SimpleNamespace(
            title="Playable result", encoded="encoded-track", source="youtube"
        )
        search = AsyncMock(return_value=[track])
        monkeypatch.setattr(wavelink.Playable, "search", search)

        result = await service.probe_search("test query")

        assert result == {
            "ok": True,
            "detail": "Loaded Playable result",
            "source": "youtube",
        }
        search.assert_awaited_once_with(
            "test query", source="ytsearch", node=service.node
        )
        await service.close()

    asyncio.run(run_test())


def test_lavalink_service_reports_an_unready_pool(monkeypatch):
    async def run_test():
        monkeypatch.setenv("LAVALINK_PASSWORD", "test-password")
        await wavelink.Pool.close()
        connect = AsyncMock(return_value={})
        monkeypatch.setattr(wavelink.Pool, "connect", connect)
        service = LavalinkService(SimpleNamespace())

        assert await service.ensure_connected() is False
        assert service.connected is False
        assert "did not become ready" in service.last_error
        connect.assert_awaited_once()
        await service.close()

    asyncio.run(run_test())


def test_lavalink_node_ready_event_clears_a_stale_timeout(monkeypatch):
    async def run_test():
        service = LavalinkService(SimpleNamespace())
        service.last_error = "Node did not become ready within 10 seconds."
        node = SimpleNamespace(
            identifier=service.identifier,
            fetch_version=AsyncMock(return_value="4.1.1"),
        )

        await service.handle_node_ready(node)

        assert service.last_error is None
        assert service.version == "4.1.1"
        assert service._node is node
        service._node = None
        await service.close()

    asyncio.run(run_test())


def test_lavalink_waits_for_ready_payload_after_websocket_connect(monkeypatch):
    async def run_test():
        monkeypatch.setenv("LAVALINK_PASSWORD", "test-password")
        monkeypatch.setenv("LAVALINK_READY_TIMEOUT", "1")
        await wavelink.Pool.close()

        async def connect(*, nodes, client):
            node = next(iter(nodes))
            node._status = wavelink.NodeStatus.CONNECTING

            async def receive_ready_payload():
                await asyncio.sleep(0.01)
                node._status = wavelink.NodeStatus.CONNECTED

            asyncio.create_task(receive_ready_payload())
            return {}

        monkeypatch.setattr(wavelink.Pool, "connect", connect)
        monkeypatch.setattr(
            wavelink.Node,
            "fetch_version",
            AsyncMock(return_value="4.1.1"),
        )
        service = LavalinkService(SimpleNamespace())

        assert await service.ensure_connected() is True
        assert service.connected is True
        assert service.version == "4.1.1"
        await service.close()

    asyncio.run(run_test())


def test_lavalink_has_safe_defaults_and_disables_itself_without_password(
    monkeypatch,
):
    async def run_test():
        monkeypatch.delenv("LAVALINK_URI", raising=False)
        monkeypatch.delenv("LAVALINK_PASSWORD", raising=False)
        service = LavalinkService(SimpleNamespace())

        assert service.uri == "http://127.0.0.1:2333"
        assert await service.ensure_connected() is False
        assert service.last_error == "LAVALINK_PASSWORD is not configured."
        await service.close()

    asyncio.run(run_test())
