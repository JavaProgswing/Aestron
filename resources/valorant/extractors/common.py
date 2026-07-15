"""Shared asynchronous download support for Valorant data extractors."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiohttp

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def save_json(
    url: str,
    destination: Path,
    *,
    headers: dict[str, str] | None = None,
) -> None:
    """Download JSON with a timeout and write it without blocking the event loop."""
    async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            payload: Any = await response.json()
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    await asyncio.to_thread(destination.write_text, serialized, encoding="utf-8")


def output_path(filename: str) -> Path:
    """Return a stable output path alongside the extractor modules."""
    return Path(__file__).resolve().parent / filename
