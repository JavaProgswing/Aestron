"""Download authenticated Valorant content identifiers from Riot."""

import asyncio
import os

from dotenv import load_dotenv

from .common import output_path, save_json


async def main() -> None:
    """Save current Valorant content identifiers beside this module."""
    load_dotenv()
    api_key = os.getenv("VAL_API_TOKEN")
    if not api_key:
        raise RuntimeError("VAL_API_TOKEN is required in the environment or .env file.")
    await save_json(
        "https://ap.api.riotgames.com/val/content/v1/contents?locale=en-US",
        output_path("valorant_ids.json"),
        headers={"X-Riot-Token": api_key},
    )


if __name__ == "__main__":
    asyncio.run(main())
