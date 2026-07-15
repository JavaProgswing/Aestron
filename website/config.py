"""Validated website configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


def _optional_url(values: dict[str, str], name: str) -> str | None:
    value = values.get(name, "").strip().rstrip("/")
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"{name} must be an absolute HTTP(S) URL.")
    return value


@dataclass(frozen=True, slots=True)
class WebsiteSettings:
    """Deployment settings for the public site, API, and Riot RSO flow."""

    base_url: str
    database_dsn: str | None
    service_token: str | None
    admin_token: str | None
    state_secret: str | None
    riot_client_id: str | None
    riot_client_secret: str | None
    riot_cluster: str
    riot_redirect_uri: str
    topgg_bot_url: str | None
    support_url: str | None
    environment: str
    allowed_hosts: tuple[str, ...]

    @classmethod
    def from_environment(
        cls, environment: dict[str, str] | None = None
    ) -> WebsiteSettings:
        """Load settings without embedding deployment credentials or identifiers."""
        values = dict(os.environ if environment is None else environment)
        base_url = _optional_url(values, "AESTRON_WEB_BASE_URL") or (
            "http://127.0.0.1:27009"
        )
        cluster = values.get("RIOT_RSO_CLUSTER", "asia").strip().lower()
        if cluster not in {"americas", "asia", "europe"}:
            raise RuntimeError(
                "RIOT_RSO_CLUSTER must be one of: americas, asia, europe."
            )
        redirect_uri = values.get("RIOT_RSO_REDIRECT_URI", "").strip()
        if not redirect_uri:
            redirect_uri = f"{base_url}/auth/riot/callback"
        parsed_redirect = urlparse(redirect_uri)
        if (
            parsed_redirect.scheme not in {"http", "https"}
            or not parsed_redirect.netloc
        ):
            raise RuntimeError("RIOT_RSO_REDIRECT_URI must be an absolute HTTP(S) URL.")

        environment_name = (
            values.get("AESTRON_ENVIRONMENT", "development").strip().lower()
        )
        if environment_name not in {"development", "staging", "production"}:
            raise RuntimeError(
                "AESTRON_ENVIRONMENT must be development, staging, or production."
            )
        if environment_name == "production" and urlparse(base_url).scheme != "https":
            raise RuntimeError("AESTRON_WEB_BASE_URL must use HTTPS in production.")
        secret_values = {
            "AESTRON_SERVICE_TOKEN": values.get("AESTRON_SERVICE_TOKEN", "").strip(),
            "AESTRON_ADMIN_TOKEN": values.get("AESTRON_ADMIN_TOKEN", "").strip(),
            "AESTRON_STATE_SECRET": values.get("AESTRON_STATE_SECRET", "").strip(),
        }
        for variable, secret_value in secret_values.items():
            if secret_value and len(secret_value) < 32:
                raise RuntimeError(f"{variable} must be at least 32 characters.")

        allowed_hosts = tuple(
            host.strip()
            for host in values.get(
                "AESTRON_ALLOWED_HOSTS",
                "aestron.yashasviallen.is-a.dev,localhost,127.0.0.1,testserver",
            ).split(",")
            if host.strip()
        )
        return cls(
            base_url=base_url,
            database_dsn=values.get("AESTRON_DATABASE_DSN", "").strip() or None,
            service_token=secret_values["AESTRON_SERVICE_TOKEN"] or None,
            admin_token=secret_values["AESTRON_ADMIN_TOKEN"] or None,
            state_secret=secret_values["AESTRON_STATE_SECRET"] or None,
            riot_client_id=values.get("RIOT_RSO_CLIENT_ID", "").strip() or None,
            riot_client_secret=(
                values.get("RIOT_RSO_CLIENT_SECRET", "").strip() or None
            ),
            riot_cluster=cluster,
            riot_redirect_uri=redirect_uri,
            topgg_bot_url=_optional_url(values, "TOPGG_BOT_URL"),
            support_url=_optional_url(values, "SUPPORT_SERVER_INVITE"),
            environment=environment_name,
            allowed_hosts=allowed_hosts or ("localhost", "127.0.0.1", "testserver"),
        )

    @property
    def rso_configured(self) -> bool:
        """Whether every secret needed for the authorization-code flow exists."""
        return all(
            (
                self.riot_client_id,
                self.riot_client_secret,
                self.state_secret,
            )
        )

    @property
    def service_api_configured(self) -> bool:
        """Whether the bot-to-website API can authenticate callers."""
        return bool(self.service_token)

    @property
    def admin_api_configured(self) -> bool:
        """Whether administrative endpoints can authenticate callers."""
        return bool(self.admin_token)
