"""Official Riot Sign On client for server-side authorization-code exchange."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

import aiohttp


class RiotAPIError(RuntimeError):
    """A sanitized Riot authentication or account API failure."""


class RiotRSOClient:
    """Exchange RSO codes and identify the player without persisting tokens."""

    authorize_endpoint = "https://auth.riotgames.com/authorize"
    token_endpoint = "https://auth.riotgames.com/token"

    def __init__(
        self,
        *,
        client_id: str | None,
        client_secret: str | None,
        api_key: str | None,
        redirect_uri: str,
        cluster: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Configure the approved RSO client and routing cluster."""
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_key = api_key
        self.redirect_uri = redirect_uri
        self.cluster = cluster
        self.session = session
        self._owns_session = False

    @property
    def configured(self) -> bool:
        """Whether client credentials are available."""
        return bool(self.client_id and self.client_secret)

    def authorization_url(self, state: str) -> str:
        """Build Riot's documented RSO authorization URL."""
        if not self.client_id:
            raise RiotAPIError("Riot Sign On is not configured.")
        parameters = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": "openid offline_access",
                "state": state,
            }
        )
        return f"{self.authorize_endpoint}?{parameters}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange one authorization code using OAuth Client Secret Basic."""
        if not self.configured:
            raise RiotAPIError("Riot Sign On is not configured.")
        session = await self._get_session()
        authorization = aiohttp.encode_basic_auth(
            self.client_id or "", self.client_secret or ""
        )
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        async with session.post(
            self.token_endpoint,
            data=data,
            headers={"Authorization": authorization},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status != 200:
                if response.status == 401:
                    raise RiotAPIError(
                        "Riot rejected the RSO client credentials (401). Verify "
                        "RIOT_RSO_CLIENT_ID and the separate RSO client secret."
                    )
                if response.status == 400:
                    raise RiotAPIError(
                        "Riot rejected the one-time code (400). It may be expired "
                        "or reused, or RIOT_RSO_REDIRECT_URI may not exactly match."
                    )
                raise RiotAPIError(
                    f"Riot rejected the token exchange ({response.status})."
                )
            payload = await response.json()
        if not payload.get("access_token"):
            raise RiotAPIError("Riot did not return an access token.")
        return payload

    async def account_me(self, access_token: str) -> dict[str, str]:
        """Resolve the opted-in Riot identity from an RSO access token."""
        session = await self._get_session()
        endpoint = (
            f"https://{self.cluster}.api.riotgames.com/riot/account/v1/accounts/me"
        )
        headers = {"Authorization": f"Bearer {access_token}"}
        async with session.get(
            endpoint,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status != 200:
                raise RiotAPIError(
                    f"Riot could not identify the linked account ({response.status})."
                )
            payload = await response.json()
        required = ("puuid", "gameName", "tagLine")
        if any(not payload.get(key) for key in required):
            raise RiotAPIError("Riot returned an incomplete account response.")
        return payload

    async def active_shard(self, puuid: str) -> str:
        """Resolve VALORANT routing with the separate Riot product API key."""
        if not self.api_key:
            raise RiotAPIError("The Riot product API key is not configured.")
        session = await self._get_session()
        endpoint = (
            f"https://{self.cluster}.api.riotgames.com/riot/account/v1/"
            f"active-shards/by-game/val/by-puuid/{quote(puuid, safe='')}"
        )
        async with session.get(
            endpoint,
            headers={"X-Riot-Token": self.api_key},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status in {401, 403}:
                raise RiotAPIError(
                    "Riot rejected the product API key during shard lookup."
                )
            if response.status != 200:
                raise RiotAPIError(
                    f"Riot could not resolve the account shard ({response.status})."
                )
            payload = await response.json()
        shard = str(payload.get("activeShard") or "").casefold()
        if shard not in {"ap", "br", "eu", "kr", "latam", "na"}:
            raise RiotAPIError("Riot returned an unsupported account shard.")
        return shard

    async def close(self) -> None:
        """Close a session created by this client."""
        if self._owns_session and self.session is not None:
            await self.session.close()
            self.session = None
            self._owns_session = False

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            self._owns_session = True
        return self.session
