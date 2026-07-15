"""Authentication helpers and signed Riot OAuth state tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Annotated

from fastapi import Header, HTTPException, Request, status


def create_oauth_state(discord_user_id: int, secret: str) -> str:
    """Create an expiring, tamper-evident state value for one Discord user."""
    payload = {
        "discord_user_id": discord_user_id,
        "issued_at": int(time.time()),
        "nonce": secrets.token_urlsafe(16),
        "version": 1,
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_encode(signature)}"


def validate_oauth_state(token: str, secret: str, *, max_age: int = 600) -> int:
    """Validate state integrity and age, returning the linked Discord user ID."""
    try:
        encoded, supplied_signature = token.split(".", maxsplit=1)
        expected_signature = hmac.new(
            secret.encode(), encoded.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_decode(supplied_signature), expected_signature):
            raise ValueError("invalid signature")
        payload = json.loads(_decode(encoded))
        issued_at = int(payload["issued_at"])
        discord_user_id = int(payload["discord_user_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("The account-link request is invalid.") from error
    age = int(time.time()) - issued_at
    if age < -30 or age > max_age:
        raise ValueError("The account-link request has expired.")
    if discord_user_id <= 0:
        raise ValueError("The Discord user ID is invalid.")
    return discord_user_id


async def require_service_token(
    request: Request,
    x_aestron_service_token: Annotated[str | None, Header()] = None,
) -> None:
    """Authenticate bot-to-website API requests."""
    expected = request.app.state.settings.service_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The service API is not configured.",
        )
    if not x_aestron_service_token or not secrets.compare_digest(
        x_aestron_service_token, expected
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token.",
        )


async def require_admin_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Authenticate administrative API requests with a bearer token."""
    expected = request.app.state.settings.admin_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The admin API is not configured.",
        )
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token.",
        )


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
