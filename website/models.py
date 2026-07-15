"""Validated request and response models for the Aestron API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LinkRequest(BaseModel):
    """A bot-authenticated request to create a Riot login URL."""

    discord_user_id: int = Field(gt=0)


class LinkResponse(BaseModel):
    """A short-lived Riot authorization URL."""

    authorization_url: str
    expires_in: int = 600


class FeedbackCreate(BaseModel):
    """A public suggestion or bug report."""

    kind: Literal["suggestion", "bug"]
    title: str = Field(min_length=4, max_length=120)
    body: str = Field(min_length=15, max_length=4000)
    contact: str | None = Field(default=None, max_length=160)
    discord_user_id: int | None = Field(default=None, gt=0)
    website: str = Field(default="", max_length=0, exclude=True)

    @field_validator("title", "body", "contact")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        """Trim form content and reject control characters."""
        if value is None:
            return None
        normalized = " ".join(value.split()) if value != "" else ""
        if any(ord(character) < 32 for character in normalized):
            raise ValueError("Control characters are not allowed.")
        return normalized


class FeedbackRecord(BaseModel):
    """Stored feedback returned to administrators."""

    id: int
    kind: str
    title: str
    body: str
    contact: str | None
    discord_user_id: int | None
    source: str
    status: str
    created_at: datetime
    updated_at: datetime


class FeedbackStatusUpdate(BaseModel):
    """Allowed administrative feedback workflow changes."""

    status: Literal["new", "reviewing", "planned", "resolved", "rejected"]
