"""Process version and uptime metadata shared by the bot and website."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any

_STARTED_AT = datetime.now(UTC)
_STARTED_MONOTONIC = time.monotonic()


def runtime_info() -> dict[str, Any]:
    """Return safe deployment metadata without reading secrets or invoking Git."""
    commit = os.getenv("AESTRON_GIT_COMMIT", "unknown").strip() or "unknown"
    return {
        "version": (
            os.getenv("AESTRON_VERSION", "").strip()
            or os.getenv("BOT_VERSION", "").strip()
            or "development"
        ),
        "git_commit": commit,
        "git_commit_short": commit[:12] if commit != "unknown" else "unknown",
        "git_branch": (os.getenv("AESTRON_GIT_BRANCH", "unknown").strip() or "unknown"),
        "started_at": _STARTED_AT.isoformat(),
        "uptime_seconds": int(time.monotonic() - _STARTED_MONOTONIC),
    }
