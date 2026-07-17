import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from website.config import WebsiteSettings
from website.main import SensitiveAccessLogFilter, create_app
from website.riot import RiotAPIError, RiotRSOClient
from website.security import validate_oauth_state

SERVICE_TOKEN = "service-secret-with-at-least-thirty-two-characters"
ADMIN_TOKEN = "admin-secret-with-at-least-thirty-two-characters"


class FakeDatabase:
    connected = False

    def __init__(self):
        self.feedback = []
        self.account = None

    async def connect(self):
        self.connected = True

    async def close(self):
        self.connected = False

    async def create_feedback(self, feedback, *, source):
        record = {
            "id": len(self.feedback) + 1,
            **feedback.model_dump(exclude={"website"}),
            "source": source,
            "status": "new",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        self.feedback.append(record)
        return record

    async def list_feedback(self, *, status, limit):
        rows = self.feedback
        if status:
            rows = [row for row in rows if row["status"] == status]
        return rows[:limit]

    async def update_feedback_status(self, feedback_id, new_status):
        for record in self.feedback:
            if record["id"] == feedback_id:
                record["status"] = new_status
                record["updated_at"] = datetime.now(UTC)
                return record
        return None

    async def feedback_counts(self):
        return {"new": len(self.feedback)}

    async def upsert_riot_account(self, **account):
        self.account = account

    async def get_riot_account(self, discord_user_id):
        if not self.account or self.account["discord_user_id"] != discord_user_id:
            return None
        return {
            "discorduserid": discord_user_id,
            "accountpuuid": self.account["puuid"],
            "accountname": self.account["game_name"],
            "accounttag": self.account["tag_line"],
            "accountregion": self.account["region"],
            "opted_in_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }

    async def delete_riot_account(self, discord_user_id):
        if self.account and self.account["discord_user_id"] == discord_user_id:
            self.account = None
            return True
        return False


class FakeRiotClient:
    def authorization_url(self, state):
        return f"https://auth.riotgames.com/authorize?state={state}"

    async def exchange_code(self, code):
        assert code == "test-code"
        return {"access_token": "transient-token"}

    async def account_me(self, access_token):
        assert access_token == "transient-token"
        return {"puuid": "puuid-1", "gameName": "Player", "tagLine": "TEST"}

    async def active_shard(self, puuid):
        assert puuid == "puuid-1"
        return "ap"

    async def close(self):
        return None


def _settings():
    return WebsiteSettings.from_environment(
        {
            "AESTRON_WEB_BASE_URL": "https://testserver",
            "AESTRON_SERVICE_TOKEN": SERVICE_TOKEN,
            "AESTRON_ADMIN_TOKEN": ADMIN_TOKEN,
            "AESTRON_STATE_SECRET": "state-secret-long-enough-for-tests",
            "RIOT_RSO_CLIENT_ID": "client-id",
            "RIOT_RSO_CLIENT_SECRET": "client-secret",
            "VAL_API_TOKEN": "product-api-key",
            "RIOT_RSO_CLUSTER": "asia",
            "AESTRON_ALLOWED_HOSTS": "testserver",
        }
    )


def _client():
    database = FakeDatabase()
    app = create_app(_settings(), database=database, riot_client=FakeRiotClient())
    return TestClient(app), database


def test_general_site_and_dedicated_valorant_pages_render(monkeypatch):
    monkeypatch.setenv("AESTRON_GIT_COMMIT", "a" * 40)
    monkeypatch.setenv(
        "AESTRON_SOURCE_REPOSITORY_URL",
        "https://github.com/example/aestron.git",
    )
    client, _ = _client()
    with client:
        home = client.get("/")
        privacy = client.get("/privacy")
        valorant = client.get("/valorant")
        dashboard = client.get("/valorant/dashboard")
        updates = client.get("/updates")
        updates_api = client.get("/api/v1/updates")

    assert home.status_code == 200
    assert "Moderation & safety" in home.text
    assert "VALORANT account linking" in privacy.text
    assert "AESTRON FOR VALORANT" in valorant.text
    assert "Riot Games" in valorant.text
    assert "prototype data" in dashboard.text
    assert "Riot Games" not in home.text
    assert home.headers["x-content-type-options"] == "nosniff"
    assert updates.status_code == 200
    assert "Social, fun, and Minecraft sessions rebuilt" in updates.text
    assert f"https://github.com/example/aestron/commit/{'a' * 40}" in updates.text
    assert updates_api.status_code == 200
    assert updates_api.json()["runtime"]["git_commit"] == "a" * 40
    assert updates_api.json()["updates"][0]["category"] == "Fleet operations"


def test_api_discovery_health_and_private_service_auth():
    client, _ = _client()
    with client:
        root = client.get("/api/")
        health = client.get("/api/health")
        denied = client.post("/api/v1/oauth/link", json={"discord_user_id": 123})
        allowed = client.post(
            "/api/v1/oauth/link",
            headers={"X-Aestron-Service-Token": SERVICE_TOKEN},
            json={"discord_user_id": 123},
        )

    assert root.status_code == 200
    assert root.json()["documentation"].endswith("/api/docs")
    assert health.json()["status"] == "healthy"
    assert denied.status_code == 401
    assert allowed.status_code == 200
    state = parse_qs(urlparse(allowed.json()["authorization_url"]).query)["state"][0]
    assert state != "123"
    assert validate_oauth_state(state, _settings().state_secret) == 123


def test_linking_requires_the_separate_product_api_key():
    settings = replace(_settings(), riot_api_key=None)
    app = create_app(settings, database=FakeDatabase(), riot_client=FakeRiotClient())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/oauth/link",
            headers={"X-Aestron-Service-Token": SERVICE_TOKEN},
            json={"discord_user_id": 123},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Riot account linking is not fully configured."


def test_oauth_callback_stores_identity_and_shard_but_no_token():
    client, database = _client()
    with client:
        link = client.post(
            "/api/v1/oauth/link",
            headers={"X-Aestron-Service-Token": SERVICE_TOKEN},
            json={"discord_user_id": 456},
        )
        state = parse_qs(urlparse(link.json()["authorization_url"]).query)["state"][0]
        callback = client.get(
            "/auth/riot/callback", params={"code": "test-code", "state": state}
        )

    assert callback.status_code == 200
    assert database.account == {
        "discord_user_id": 456,
        "puuid": "puuid-1",
        "game_name": "Player",
        "tag_line": "TEST",
        "region": "ap",
    }
    assert "token" not in repr(database.account).lower()


def test_oauth_callback_query_is_redacted_from_access_logs():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:1234",
            "GET",
            "/auth/riot/callback?code=secret-code&state=signed-state",
            "1.1",
            200,
        ),
        None,
    )

    assert SensitiveAccessLogFilter().filter(record) is True
    assert record.args[2] == "/auth/riot/callback?<redacted>"
    assert "secret-code" not in record.getMessage()
    assert "signed-state" not in record.getMessage()


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (401, "RSO client credentials"),
        (400, "expired or reused"),
        (503, "token exchange (503)"),
    ],
)
def test_riot_token_exchange_returns_actionable_sanitized_errors(status_code, message):
    class FakeResponse:
        status = status_code

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class FakeSession:
        closed = False

        def post(self, *args, **kwargs):
            return FakeResponse()

    async def exchange():
        client = RiotRSOClient(
            client_id="client-id",
            client_secret="client-secret",
            api_key="product-api-key",
            redirect_uri="https://example.com/auth/riot/callback",
            cluster="asia",
            session=FakeSession(),
        )
        with pytest.raises(RiotAPIError) as captured:
            await client.exchange_code("single-use-code")
        assert message in str(captured.value)

    asyncio.run(exchange())


def test_active_shard_uses_product_key_header_not_query_string():
    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self):
            return {
                "puuid": "player/one",
                "game": "val",
                "activeShard": "ap",
            }

    class FakeSession:
        closed = False
        url = None
        headers = None

        def get(self, url, *, headers, timeout):
            self.url = url
            self.headers = headers
            return FakeResponse()

    async def resolve():
        session = FakeSession()
        client = RiotRSOClient(
            client_id="client-id",
            client_secret="client-secret",
            api_key="product-api-key",
            redirect_uri="https://example.com/auth/riot/callback",
            cluster="asia",
            session=session,
        )

        assert await client.active_shard("player/one") == "ap"
        assert session.headers == {"X-Riot-Token": "product-api-key"}
        assert "api_key" not in session.url
        assert session.url.endswith("/player%2Fone")

    asyncio.run(resolve())


def test_feedback_validation_sources_and_admin_auth():
    client, _ = _client()
    payload = {
        "kind": "suggestion",
        "title": "Queue history",
        "body": "Please add a short history of recently played songs.",
    }
    with client:
        public = client.post("/api/v1/feedback", json=payload)
        bot = client.post(
            "/api/v1/bot/feedback",
            headers={"X-Aestron-Service-Token": SERVICE_TOKEN},
            json={**payload, "discord_user_id": 123},
        )
        denied = client.get("/api/v1/admin/feedback")
        admin = client.get(
            "/api/v1/admin/feedback",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )

    assert public.status_code == 201
    assert public.json()["source"] == "website"
    assert bot.status_code == 201
    assert bot.json()["source"] == "discord"
    assert denied.status_code == 401
    assert len(admin.json()) == 2
