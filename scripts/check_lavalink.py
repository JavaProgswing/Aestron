"""Verify that Lavalink can load an encoded track without starting Discord."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

import aiohttp
from dotenv import load_dotenv


async def fetch_json(
    session: aiohttp.ClientSession, url: str, **kwargs: Any
) -> dict[str, Any]:
    """Fetch one required Lavalink JSON response."""
    async with session.get(url, **kwargs) as response:
        response.raise_for_status()
        return await response.json()


async def check_lavalink(query: str) -> dict[str, Any]:
    """Check authentication, server capabilities, and one playable result."""
    uri = os.getenv("LAVALINK_URI", "http://127.0.0.1:2333").rstrip("/")
    password = os.getenv("LAVALINK_PASSWORD", "").strip()
    if not password:
        raise RuntimeError("LAVALINK_PASSWORD is not configured.")
    source = os.getenv("LAVALINK_SEARCH_SOURCE", "ytsearch")
    timeout = aiohttp.ClientTimeout(total=20)
    headers = {"Authorization": password}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(f"{uri}/version") as response:
            response.raise_for_status()
            version = (await response.text()).strip()
        info = await fetch_json(session, f"{uri}/v4/info")
        tracks = await fetch_json(
            session,
            f"{uri}/v4/loadtracks",
            params={"identifier": f"{source}:{query}"},
        )

    data = tracks.get("data")
    first_track = data[0] if isinstance(data, list) and data else None
    if tracks.get("loadType") not in {"track", "search", "playlist"}:
        raise RuntimeError(
            f"Lavalink returned loadType={tracks.get('loadType')!r}: {data}"
        )
    if not first_track or not first_track.get("encoded"):
        raise RuntimeError("Lavalink did not return an encoded playable track.")

    plugins = {
        plugin.get("name"): plugin.get("version") for plugin in info.get("plugins", [])
    }
    track_info = first_track.get("info", {})
    return {
        "ok": True,
        "lavalink_version": version,
        "plugins": plugins,
        "source_managers": info.get("sourceManagers", []),
        "search_source": source,
        "load_type": tracks.get("loadType"),
        "track": track_info.get("title"),
        "track_source": track_info.get("sourceName"),
        "encoded_track": True,
    }


async def async_main() -> int:
    """Run the asynchronous command-line check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "query", nargs="?", default="Aestron playback test", help="Search query"
    )
    args = parser.parse_args()
    try:
        result = await check_lavalink(args.query)
    except (aiohttp.ClientError, TimeoutError, RuntimeError) as error:
        print(
            json.dumps(
                {"ok": False, "error": f"{type(error).__name__}: {error}"},
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> int:
    """Load local configuration and run the checker."""
    load_dotenv()
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
