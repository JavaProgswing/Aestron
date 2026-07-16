"""Process version and uptime metadata shared by the bot and website."""

from __future__ import annotations

import os
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_STARTED_AT = datetime.now(UTC)
_STARTED_MONOTONIC = time.monotonic()


def _public_repository_url() -> str | None:
    """Return a credential-free browser URL for the configured Git remote."""
    value = next(
        (
            os.getenv(name, "").strip()
            for name in (
                "AESTRON_SOURCE_REPOSITORY_URL",
                "DEPLOY_GIT_REMOTE_URL",
                "GIT_ADDRESS",
                "GIT_REPO_ADDRESS",
            )
            if os.getenv(name, "").strip()
        ),
        "",
    )
    if not value:
        return None

    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"}:
        if parsed.username or parsed.password or not parsed.hostname:
            return None
        path = parsed.path.removesuffix(".git").rstrip("/")
        return urlunsplit(("https", parsed.netloc, path, "", ""))
    if parsed.scheme == "ssh" and parsed.hostname and not parsed.password:
        path = parsed.path.removesuffix(".git").rstrip("/")
        return urlunsplit(("https", parsed.hostname, path, "", ""))
    return None


def runtime_info() -> dict[str, Any]:
    """Return safe deployment metadata without reading secrets or invoking Git."""
    commit = os.getenv("AESTRON_GIT_COMMIT", "unknown").strip() or "unknown"
    repository_url = _public_repository_url()
    commit_url = None
    if repository_url and re.fullmatch(r"[0-9a-fA-F]{7,64}", commit):
        commit_url = f"{repository_url}/commit/{commit}"
    return {
        "version": (
            os.getenv("AESTRON_VERSION", "").strip()
            or os.getenv("BOT_VERSION", "").strip()
            or "development"
        ),
        "git_commit": commit,
        "git_commit_short": commit[:12] if commit != "unknown" else "unknown",
        "git_branch": (os.getenv("AESTRON_GIT_BRANCH", "unknown").strip() or "unknown"),
        "repository_url": repository_url,
        "git_commit_url": commit_url,
        "started_at": _STARTED_AT.isoformat(),
        "uptime_seconds": int(time.monotonic() - _STARTED_MONOTONIC),
    }
