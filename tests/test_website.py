from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from website.config import WebsiteSettings
from website.main import create_app
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

    async def active_shard(self, access_token, puuid):
        assert (access_token, puuid) == ("transient-token", "puuid-1")
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
            "RIOT_RSO_CLUSTER": "asia",
            "AESTRON_ALLOWED_HOSTS": "testserver",
        }
    )


def _client():
    database = FakeDatabase()
    app = create_app(_settings(), database=database, riot_client=FakeRiotClient())
    return TestClient(app), database


def test_general_site_and_dedicated_valorant_pages_render():
    client, _ = _client()
    with client:
        home = client.get("/")
        privacy = client.get("/privacy")
        valorant = client.get("/valorant")
        dashboard = client.get("/valorant/dashboard")

    assert home.status_code == 200
    assert "Moderation & safety" in home.text
    assert "VALORANT account linking" in privacy.text
    assert "AESTRON FOR VALORANT" in valorant.text
    assert "Riot Games" in valorant.text
    assert "prototype data" in dashboard.text
    assert "Riot Games" not in home.text
    assert home.headers["x-content-type-options"] == "nosniff"


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
