"""Runtime configuration validation tests."""

import pytest

from aestron_bot.settings import DatabaseSettings, RuntimeSettings


def test_database_settings_report_all_missing_values():
    with pytest.raises(RuntimeError, match="DATABASE_NAME.*DATABASE_PASSWORD"):
        DatabaseSettings.from_environment({})


def test_database_settings_validate_port():
    environment = {
        "DATABASE_URL": "localhost",
        "DATABASE_PORT": "70000",
        "DATABASE_NAME": "aestron",
        "DATABASE_USERNAME": "bot",
        "DATABASE_PASSWORD": "secret",
    }
    with pytest.raises(RuntimeError, match="between 1 and 65535"):
        DatabaseSettings.from_environment(environment)


def test_database_settings_encode_credentials_in_dsn():
    settings = DatabaseSettings.from_environment(
        {
            "DATABASE_URL": "db.example.com",
            "DATABASE_PORT": "5432",
            "DATABASE_NAME": "aestron data",
            "DATABASE_USERNAME": "bot@example.com",
            "DATABASE_PASSWORD": "a/b:c",
        }
    )
    assert settings.dsn == (
        "postgresql://bot%40example.com:a%2Fb%3Ac@db.example.com:5432/aestron%20data"
    )


def test_runtime_settings_have_safe_project_agnostic_defaults():
    settings = RuntimeSettings.from_environment({})
    assert settings.owner_ids == frozenset()
    assert settings.error_logging_channel_id is None
    assert settings.bug_logging_channel_id is None
    assert settings.development_channel_id is None
    assert settings.support_server_invite is None
    assert settings.default_prefix == "a!"
    assert settings.version == "development"
    assert settings.sync_commands_on_startup is True


def test_runtime_settings_parse_optional_values():
    settings = RuntimeSettings.from_environment(
        {
            "BOT_OWNER_IDS": "123, 456,123",
            "CHANNEL_DEV_ID": "789",
            "SUPPORT_SERVER_INVITE": "https://discord.gg/example",
            "DEFAULT_PREFIX": "!",
            "BOT_VERSION": "3.0.0",
        }
    )
    assert settings.owner_ids == frozenset({123, 456})
    assert settings.development_channel_id == 789
    assert settings.support_server_invite == "https://discord.gg/example"
    assert settings.default_prefix == "!"
    assert settings.version == "3.0.0"


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"BOT_OWNER_IDS": "abc"}, "BOT_OWNER_IDS"),
        ({"CHANNEL_DEV_ID": "-1"}, "positive"),
        ({"SUPPORT_SERVER_INVITE": "https://example.com"}, "Discord invite"),
        ({"DEFAULT_PREFIX": ""}, "DEFAULT_PREFIX"),
        ({"AESTRON_SITE_BASE_URL": "not-a-url"}, "absolute HTTP"),
        ({"AESTRON_SERVICE_TOKEN": "too-short"}, "at least 32"),
        ({"SYNC_COMMANDS_ON_STARTUP": "sometimes"}, "must be one of"),
    ],
)
def test_runtime_settings_reject_invalid_values(environment, message):
    with pytest.raises(RuntimeError, match=message):
        RuntimeSettings.from_environment(environment)
