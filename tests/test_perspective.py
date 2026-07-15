import asyncio

import main


class FakeResponse:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    def raise_for_status(self):
        return None

    async def json(self):
        return {"attributeScores": {"PROFANITY": {}}}


class FakeSession:
    def __init__(self):
        self.request = None

    def post(self, url, **kwargs):
        self.request = (url, kwargs)
        return FakeResponse()


def test_analyze_message_uses_async_rest_api_without_storing_comments(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(main.client, "session", session)
    monkeypatch.setattr(main.client, "perspective_api_key", "test-api-key")

    result = asyncio.run(main.analyze_message("example", ["PROFANITY"]))

    assert "attributeScores" in result
    url, request = session.request
    assert url == main.PERSPECTIVE_ANALYZE_URL
    assert request["params"] == {"key": "test-api-key"}
    assert request["json"] == {
        "comment": {"text": "example"},
        "requestedAttributes": {"PROFANITY": {}},
        "doNotStore": True,
    }
