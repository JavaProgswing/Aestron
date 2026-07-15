"""Download current Valorant player-card metadata."""

import asyncio

from .common import output_path, save_json


async def main() -> None:
    """Save player-card metadata beside this module."""
    await save_json(
        "https://valorant-api.com/v1/playercards",
        output_path("player_card_info.json"),
    )


if __name__ == "__main__":
    asyncio.run(main())
