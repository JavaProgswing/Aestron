"""Cached public VALORANT artwork used by post-match dashboard renderers."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .valorant_analytics import PlayerSummary

LOGGER = logging.getLogger(__name__)
API_BASE = "https://valorant-api.com/v1"
SAFE_ID = re.compile(r"^[a-zA-Z0-9-]{8,80}$")


@dataclass(frozen=True, slots=True)
class MapArtwork:
    """Minimap art and the game-coordinate transform supplied with it."""

    display_icon: bytes
    splash: bytes
    x_multiplier: float
    y_multiplier: float
    x_scalar: float
    y_scalar: float


@dataclass(frozen=True, slots=True)
class EquipmentArtwork:
    """One current weapon or shield with its public store metadata."""

    display_name: str
    display_icon: bytes
    kill_stream_icon: bytes
    cost: int
    category: str


@dataclass(slots=True)
class ValorantArtwork:
    """Bounded artwork required by one interactive stats session."""

    maps: dict[str, MapArtwork] = field(default_factory=dict)
    agents: dict[str, bytes] = field(default_factory=dict)
    cards: dict[str, bytes] = field(default_factory=dict)
    weapons: dict[str, EquipmentArtwork] = field(default_factory=dict)
    gear: dict[str, EquipmentArtwork] = field(default_factory=dict)


class ValorantAssetService:
    """Fetch valorant-api.com metadata and media with process-local caching."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Use the bot's shared asynchronous HTTP session."""
        self.session = session
        self._json_cache: dict[str, tuple[float, Any]] = {}
        self._media_cache: dict[str, tuple[float, bytes]] = {}
        self._lock = asyncio.Lock()

    async def load(self, summary: PlayerSummary) -> ValorantArtwork:
        """Load only artwork referenced by this bounded match sample."""
        artwork = ValorantArtwork()
        try:
            maps_payload = await self._json("/maps", ttl=6 * 60 * 60)
        except (aiohttp.ClientError, TimeoutError, ValueError):
            LOGGER.warning("VALORANT artwork metadata is unavailable", exc_info=True)
            return artwork

        maps = maps_payload if isinstance(maps_payload, list) else []
        map_lookup: dict[str, dict[str, Any]] = {}
        for item in maps:
            if not isinstance(item, dict):
                continue
            for key in ("uuid", "mapUrl", "assetPath", "displayName"):
                value = str(item.get(key) or "").casefold()
                if value:
                    map_lookup[value] = item

        matches = summary.performances
        map_items = {
            match.map_id: map_lookup.get(match.map_id.casefold())
            or map_lookup.get(match.map_name.casefold())
            for match in matches
        }
        agent_ids = {
            match.agent_id for match in matches if SAFE_ID.fullmatch(match.agent_id)
        }
        card_ids = {
            match.player_card_id
            for match in matches
            if SAFE_ID.fullmatch(match.player_card_id)
        }
        weapon_ids = {
            event.weapon_id
            for match in matches
            for event in match.kill_locations
            if SAFE_ID.fullmatch(event.weapon_id)
        }
        weapon_ids.update(
            detail.weapon
            for match in matches
            for detail in match.round_details
            if SAFE_ID.fullmatch(detail.weapon)
        )
        gear_ids = {
            detail.armor
            for match in matches
            for detail in match.round_details
            if SAFE_ID.fullmatch(detail.armor)
        }

        tasks = []
        labels = []
        for map_id, item in map_items.items():
            if item:
                labels.append(("map", map_id, item))
                tasks.append(self._load_map(item))
        for category, identifiers in (
            ("agent", agent_ids),
            ("card", card_ids),
            ("weapon", weapon_ids),
            ("gear", gear_ids),
        ):
            endpoint = {
                "agent": "agents",
                "card": "playercards",
                "weapon": "weapons",
                "gear": "gear",
            }[category]
            for identifier in identifiers:
                labels.append((category, identifier, None))
                tasks.append(self._load_item(endpoint, identifier, category))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for (category, identifier, _), result in zip(labels, results, strict=True):
            if isinstance(result, Exception) or result is None:
                continue
            if category == "map":
                artwork.maps[identifier] = result
            elif category == "agent":
                artwork.agents[identifier] = result
            elif category == "card":
                artwork.cards[identifier] = result
            elif category == "weapon":
                artwork.weapons[identifier] = result
            else:
                artwork.gear[identifier] = result
        return artwork

    async def _load_map(self, item: dict[str, Any]) -> MapArtwork | None:
        icon_url = str(item.get("displayIcon") or "")
        splash_url = str(item.get("splash") or "")
        if not icon_url.startswith("https://media.valorant-api.com/"):
            return None
        icon, splash = await asyncio.gather(
            self._media(icon_url),
            self._media(splash_url) if splash_url else asyncio.sleep(0, result=b""),
        )
        return MapArtwork(
            display_icon=icon,
            splash=splash,
            x_multiplier=float(item.get("xMultiplier") or 0),
            y_multiplier=float(item.get("yMultiplier") or 0),
            x_scalar=float(item.get("xScalarToAdd") or 0),
            y_scalar=float(item.get("yScalarToAdd") or 0),
        )

    async def _load_item(
        self, endpoint: str, identifier: str, category: str
    ) -> bytes | EquipmentArtwork | None:
        payload = await self._json(f"/{endpoint}/{identifier}", ttl=12 * 60 * 60)
        if not isinstance(payload, dict):
            return None
        if category in {"weapon", "gear"}:
            display_url = str(payload.get("displayIcon") or "")
            kill_stream_url = str(payload.get("killStreamIcon") or "")
            if not display_url.startswith("https://media.valorant-api.com/"):
                return None
            display_icon, kill_stream_icon = await asyncio.gather(
                self._media(display_url),
                self._media(kill_stream_url)
                if kill_stream_url.startswith("https://media.valorant-api.com/")
                else asyncio.sleep(0, result=b""),
            )
            shop_data = payload.get("shopData") or {}
            return EquipmentArtwork(
                display_name=str(payload.get("displayName") or "Unknown equipment"),
                display_icon=display_icon,
                kill_stream_icon=kill_stream_icon,
                cost=int(shop_data.get("cost") or 0),
                category=str(
                    shop_data.get("categoryText")
                    or shop_data.get("category")
                    or category
                ),
            )
        key = {
            "agent": "fullPortraitV2",
            "card": "wideArt",
        }[category]
        url = str(payload.get(key) or payload.get("displayIcon") or "")
        if not url.startswith("https://media.valorant-api.com/"):
            return None
        return await self._media(url)

    async def _json(self, path: str, *, ttl: float) -> Any:
        now = time.monotonic()
        cached = self._json_cache.get(path)
        if cached and now - cached[0] < ttl:
            return cached[1]
        async with self._lock:
            cached = self._json_cache.get(path)
            if cached and now - cached[0] < ttl:
                return cached[1]
            async with self.session.get(
                f"{API_BASE}{path}", timeout=aiohttp.ClientTimeout(total=7)
            ) as response:
                response.raise_for_status()
                envelope = await response.json(content_type=None)
            if not isinstance(envelope, dict) or envelope.get("status") != 200:
                raise ValueError("VALORANT artwork API returned an invalid envelope")
            payload = envelope.get("data")
            self._json_cache[path] = (now, payload)
            return payload

    async def _media(self, url: str) -> bytes:
        now = time.monotonic()
        cached = self._media_cache.get(url)
        if cached and now - cached[0] < 24 * 60 * 60:
            return cached[1]
        async with self.session.get(
            url, timeout=aiohttp.ClientTimeout(total=8)
        ) as response:
            response.raise_for_status()
            if response.content_length and response.content_length > 5_000_000:
                raise ValueError("VALORANT artwork exceeds the media size limit")
            content = await response.read()
        if len(content) > 5_000_000:
            raise ValueError("VALORANT artwork exceeds the media size limit")
        self._media_cache[url] = (now, content)
        return content
