"""Download current Valorant weapon metadata."""

import asyncio

from .common import output_path, save_json


async def main() -> None:
    """Save weapon metadata beside this module."""
    await save_json(
        "https://valorant-api.com/v1/weapons",
        output_path("weapon_info.json"),
    )


if __name__ == "__main__":
    asyncio.run(main())
