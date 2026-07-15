"""Lavalink connection management for Aestron's Wavelink music player."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import TYPE_CHECKING, Any

import aiohttp
import wavelink

if TYPE_CHECKING:
    from discord.ext import commands


LOGGER = logging.getLogger(__name__)


class LavalinkService:
    """Own the Lavalink node lifecycle and expose actionable health details."""

    def __init__(self, bot: commands.Bot) -> None:
        """Configure the service from environment variables."""
        self.bot = bot
        self.uri = os.getenv("LAVALINK_URI", "http://127.0.0.1:2333").rstrip("/")
        self.password = os.getenv("LAVALINK_PASSWORD", "").strip()
        self.search_source = os.getenv("LAVALINK_SEARCH_SOURCE", "ytsearch")
        self.identifier = os.getenv("LAVALINK_NODE_IDENTIFIER", "aestron-main")
        try:
            self.reconnect_interval = max(
                10, int(os.getenv("LAVALINK_RECONNECT_INTERVAL", "30"))
            )
        except ValueError:
            self.reconnect_interval = 30
            LOGGER.warning("Invalid LAVALINK_RECONNECT_INTERVAL; using 30 seconds")
        try:
            self.ready_timeout = max(
                1.0, float(os.getenv("LAVALINK_READY_TIMEOUT", "10"))
            )
        except ValueError:
            self.ready_timeout = 10.0
            LOGGER.warning("Invalid LAVALINK_READY_TIMEOUT; using 10 seconds")
        self._node: wavelink.Node | None = None
        self._connect_lock = asyncio.Lock()
        self._reconnect_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._session: aiohttp.ClientSession | None = None
        self._owns_session = False
        self.last_error: str | None = None
        self.version: str | None = None
        self.last_probe: dict[str, Any] | None = None

    @property
    def node(self) -> wavelink.Node | None:
        """Return the connected node, if one is currently ready."""
        nodes = wavelink.Pool.nodes
        node = nodes.get(self.identifier)
        if node is not None and node.status is wavelink.NodeStatus.CONNECTED:
            return node
        if (
            self._node is not None
            and self._node.status is wavelink.NodeStatus.CONNECTED
        ):
            return self._node
        return None

    @property
    def connected(self) -> bool:
        """Whether a Lavalink node is ready for searches and playback."""
        return self.node is not None

    async def start(self) -> None:
        """Attempt the initial connection and start background reconnection."""
        await self.ensure_connected()
        if self._reconnect_task is None or self._reconnect_task.done():
            self._stop_event.clear()
            self._reconnect_task = asyncio.create_task(
                self._reconnect_loop(), name="aestron-lavalink-reconnect"
            )

    async def ensure_connected(self) -> bool:
        """Connect or reconnect the configured Lavalink v4 node."""
        if not self.password:
            self.last_error = "LAVALINK_PASSWORD is not configured."
            LOGGER.warning("Lavalink is disabled: %s", self.last_error)
            return False
        if self.connected:
            return True

        async with self._connect_lock:
            if self.connected:
                return True

            if self._node is None:
                self._session = getattr(self.bot, "session", None)
                if self._session is None:
                    self._session = aiohttp.ClientSession()
                    self._owns_session = True
                self._node = wavelink.Node(
                    identifier=self.identifier,
                    uri=self.uri,
                    password=self.password,
                    session=self._session,
                    retries=3,
                    inactive_player_timeout=300,
                )

            LOGGER.info(
                "Connecting to Lavalink node %s at %s", self.identifier, self.uri
            )
            try:
                if self.identifier in wavelink.Pool.nodes:
                    await wavelink.Pool.reconnect()
                else:
                    await wavelink.Pool.connect(nodes=[self._node], client=self.bot)
            except Exception as error:
                self.last_error = f"{type(error).__name__}: {error}"
                LOGGER.exception("Lavalink connection attempt raised an exception")
                return False

            node = await self._wait_until_ready()
            if node is None:
                self.last_error = (
                    f"Node did not become ready within {self.ready_timeout:g} seconds. "
                    "Verify LAVALINK_URI, LAVALINK_PASSWORD, and Lavalink v4."
                )
                LOGGER.warning("Lavalink is unavailable: %s", self.last_error)
                return False

            self.last_error = None
            try:
                self.version = await asyncio.wait_for(node.fetch_version(), timeout=5)
            except Exception:
                LOGGER.warning(
                    "Connected to Lavalink, but its version could not be read"
                )
            LOGGER.info(
                "Lavalink node %s is ready (version=%s)",
                node.identifier,
                self.version or "unknown",
            )
            return True

    async def _wait_until_ready(self) -> wavelink.Node | None:
        """Wait for Lavalink's ready payload after its WebSocket opens."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.ready_timeout

        while loop.time() < deadline:
            node = self.node
            if node is not None:
                return node

            # Wavelink marks a failed or exhausted connection as disconnected.
            # Waiting longer cannot make that attempt ready; the reconnect loop
            # will perform the next attempt at its configured interval.
            if (
                self._node is not None
                and self._node.status is wavelink.NodeStatus.DISCONNECTED
            ):
                return None

            await asyncio.sleep(0.1)

        return self.node

    async def health(self, *, refresh: bool = False) -> dict[str, Any]:
        """Return a small diagnostic snapshot without blocking the bot loop."""
        node = self.node
        if refresh and node is not None:
            try:
                self.version = await asyncio.wait_for(node.fetch_version(), timeout=5)
            except Exception as error:
                self.last_error = f"{type(error).__name__}: {error}"

        return {
            "connected": node is not None,
            "identifier": node.identifier if node else self.identifier,
            "uri": self.uri,
            "version": self.version or "unknown",
            "players": len(node.players) if node else 0,
            "search_source": self.search_source,
            "last_error": self.last_error,
            "last_probe": self.last_probe,
        }

    async def probe_search(
        self, query: str = "Aestron playback test"
    ) -> dict[str, Any]:
        """Load one encoded track to verify the configured search source."""
        if not await self.ensure_connected():
            result = {
                "ok": False,
                "detail": self.last_error or "Lavalink is not connected.",
            }
            self.last_probe = result
            return result

        try:
            results = await asyncio.wait_for(
                wavelink.Playable.search(
                    query, source=self.search_source, node=self.node
                ),
                timeout=15,
            )
            if isinstance(results, wavelink.Playlist):
                track = results.tracks[0] if results.tracks else None
            else:
                track = results[0] if results else None
            if track is None:
                result = {"ok": False, "detail": "The search returned no tracks."}
            elif not track.encoded:
                result = {
                    "ok": False,
                    "detail": "The loaded track did not include playable data.",
                }
            else:
                result = {
                    "ok": True,
                    "detail": f"Loaded {track.title}",
                    "source": track.source,
                }
        except (TimeoutError, wavelink.WavelinkException) as error:
            result = {
                "ok": False,
                "detail": f"{type(error).__name__}: {error}",
            }
            LOGGER.warning("Lavalink search probe failed: %s", result["detail"])
        self.last_probe = result
        return result

    async def close(self) -> None:
        """Stop reconnection and close every Wavelink node cleanly."""
        self._stop_event.set()
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None
        node_was_pooled = self.identifier in wavelink.Pool.nodes
        with contextlib.suppress(Exception):
            await wavelink.Pool.close()
        if self._node is not None and not node_was_pooled:
            with contextlib.suppress(Exception):
                await self._node.close()
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def _reconnect_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.reconnect_interval
                )
            except TimeoutError:
                if not self.connected:
                    await self.ensure_connected()
