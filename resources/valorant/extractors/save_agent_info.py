"""Download current playable Valorant agent metadata."""

import asyncio

from .common import output_path, save_json


async def main() -> None:
    """Save playable agent metadata beside this module."""
    await save_json(
        "https://valorant-api.com/v1/agents?isPlayableCharacter=true",
        output_path("agent_info.json"),
    )


if __name__ == "__main__":
    asyncio.run(main())
