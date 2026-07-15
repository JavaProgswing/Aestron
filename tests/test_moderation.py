"""Moderation validation tests."""

from datetime import timedelta

import pytest
from discord.ext import commands

from aestron_bot.moderation import parse_duration


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("30m", timedelta(minutes=30)),
        ("2h", timedelta(hours=2)),
        ("1d12h", timedelta(days=1, hours=12)),
        ("1w", timedelta(weeks=1)),
    ],
)
def test_parse_duration_accepts_compact_discord_durations(value, expected):
    assert parse_duration(value) == expected


@pytest.mark.parametrize("value", ["", "30", "-1h", "29d", "1hour", "0m"])
def test_parse_duration_rejects_invalid_or_unsafe_values(value):
    with pytest.raises(commands.BadArgument):
        parse_duration(value)
