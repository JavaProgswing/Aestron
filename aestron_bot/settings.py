"""Validated environment-backed runtime settings."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote, urlparse


def _optional_snowflake(values: Mapping[str, str], name: str) -> int | None:
    raw_value = values.get(name, "").strip()
    if not raw_value:
        return None
    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a Discord snowflake integer.") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive Discord snowflake integer.")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Safe operational settings; optional integrations are disabled when unset."""

    owner_ids: frozenset[int]
    error_logging_channel_id: int | None
    bug_logging_channel_id: int | None
    feedback_channel_id: int | None
    development_channel_id: int | None
    support_server_invite: str | None
    default_prefix: str
    version: str
    site_base_url: str | None
    aestron_service_token: str | None

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> RuntimeSettings:
        """Parse optional bot settings without project-specific fallback IDs."""
        values = os.environ if environment is None else environment
        owner_ids: set[int] = set()
        for raw_owner_id in values.get("BOT_OWNER_IDS", "").split(","):
            raw_owner_id = raw_owner_id.strip()
            if not raw_owner_id:
                continue
            try:
                owner_id = int(raw_owner_id)
            except ValueError as error:
                raise RuntimeError(
                    "BOT_OWNER_IDS must be comma-separated Discord snowflakes."
                ) from error
            if owner_id <= 0:
                raise RuntimeError("BOT_OWNER_IDS must contain positive integers.")
            owner_ids.add(owner_id)

        support_invite = values.get("SUPPORT_SERVER_INVITE", "").strip() or None
        if support_invite is not None and not support_invite.startswith(
            ("https://discord.gg/", "https://discord.com/invite/")
        ):
            raise RuntimeError("SUPPORT_SERVER_INVITE must be a Discord invite URL.")

        default_prefix = values.get("DEFAULT_PREFIX", "a!").strip()
        if not 1 <= len(default_prefix) <= 10:
            raise RuntimeError("DEFAULT_PREFIX must contain 1 to 10 characters.")

        site_base_url = values.get("AESTRON_SITE_BASE_URL", "").strip().rstrip("/")
        if site_base_url:
            parsed_site_url = urlparse(site_base_url)
            if (
                parsed_site_url.scheme not in {"http", "https"}
                or not parsed_site_url.netloc
            ):
                raise RuntimeError(
                    "AESTRON_SITE_BASE_URL must be an absolute HTTP(S) URL."
                )
        service_token = values.get("AESTRON_SERVICE_TOKEN", "").strip()
        if service_token and len(service_token) < 32:
            raise RuntimeError("AESTRON_SERVICE_TOKEN must be at least 32 characters.")

        return cls(
            owner_ids=frozenset(owner_ids),
            error_logging_channel_id=_optional_snowflake(
                values, "CHANNEL_ERROR_LOGGING_ID"
            ),
            bug_logging_channel_id=_optional_snowflake(
                values, "CHANNEL_BUG_LOGGING_ID"
            ),
            feedback_channel_id=_optional_snowflake(values, "CHANNEL_FEEDBACK_ID"),
            development_channel_id=_optional_snowflake(values, "CHANNEL_DEV_ID"),
            support_server_invite=support_invite,
            default_prefix=default_prefix,
            version=(
                values.get("AESTRON_VERSION", "").strip()
                or values.get("BOT_VERSION", "").strip()
                or "development"
            ),
            site_base_url=site_base_url or None,
            aestron_service_token=service_token or None,
        )


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """PostgreSQL settings required to create the async connection pool."""

    host: str
    port: int
    name: str
    username: str
    password: str

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> DatabaseSettings:
        """Load settings and fail early with all missing or invalid fields."""
        values = os.environ if environment is None else environment
        names = {
            "host": "DATABASE_URL",
            "port": "DATABASE_PORT",
            "name": "DATABASE_NAME",
            "username": "DATABASE_USERNAME",
            "password": "DATABASE_PASSWORD",
        }
        missing = [variable for variable in names.values() if not values.get(variable)]
        if missing:
            raise RuntimeError(
                "Missing required database settings: " + ", ".join(sorted(missing))
            )
        try:
            port = int(values[names["port"]])
        except ValueError as error:
            raise RuntimeError("DATABASE_PORT must be an integer.") from error
        if not 1 <= port <= 65535:
            raise RuntimeError("DATABASE_PORT must be between 1 and 65535.")
        return cls(
            host=values[names["host"]],
            port=port,
            name=values[names["name"]],
            username=values[names["username"]],
            password=values[names["password"]],
        )

    @property
    def dsn(self) -> str:
        """Build a credential-safe PostgreSQL DSN with encoded components."""
        username = quote(self.username, safe="")
        password = quote(self.password, safe="")
        database = quote(self.name, safe="")
        return f"postgresql://{username}:{password}@{self.host}:{self.port}/{database}"
