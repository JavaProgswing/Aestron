"""Download current Valorant map metadata."""

import asyncio

from .common import output_path, save_json


async def main() -> None:
    """Save map metadata beside this module."""
    await save_json(
        "https://valorant-api.com/v1/maps",
        output_path("map_info.json"),
    )


if __name__ == "__main__":
    asyncio.run(main())
