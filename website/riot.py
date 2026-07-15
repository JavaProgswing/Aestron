"""Official Riot Sign On client for server-side authorization-code exchange."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

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
        redirect_uri: str,
        cluster: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Configure the approved RSO client and routing cluster."""
        self.client_id = client_id
        self.client_secret = client_secret
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
        auth = aiohttp.BasicAuth(self.client_id or "", self.client_secret or "")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        async with session.post(
            self.token_endpoint,
            data=data,
            auth=auth,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status != 200:
                raise RiotAPIError(
                    f"Riot rejected the authorization code ({response.status})."
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

    async def active_shard(self, access_token: str, puuid: str) -> str:
        """Resolve the platform routing shard while the RSO token is transient."""
        session = await self._get_session()
        endpoint = (
            f"https://{self.cluster}.api.riotgames.com/riot/account/v1/"
            f"active-shards/by-game/val/by-puuid/{puuid}"
        )
        async with session.get(
            endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status != 200:
                raise RiotAPIError(
                    f"Riot could not resolve the account shard ({response.status})."
                )
            payload = await response.json()
        shard = str(payload.get("activeShard") or "").lower()
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
