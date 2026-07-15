import asyncio

from aestron_bot.statistics import BotStatistics


def test_statistics_collect_in_memory_without_per_command_database_io():
    statistics = BotStatistics()
    statistics.record_command("play")
    statistics.record_command("play")
    statistics.record_command("stats")
    statistics.record_outcome(succeeded=True)
    statistics.record_outcome(succeeded=False)
    statistics.record_guild_join()
    statistics.record_guild_remove()

    snapshot = statistics.snapshot()
    assert snapshot["commands_used"] == 3
    assert snapshot["commands_succeeded"] == 1
    assert snapshot["commands_failed"] == 1
    assert snapshot["guilds_joined"] == 1
    assert snapshot["guilds_left"] == 1
    assert snapshot["top_commands"][0] == ("play", 2)
    assert snapshot["persistent"] is False

    asyncio.run(statistics.close())
