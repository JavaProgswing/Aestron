"""Curated public release notes for the Aestron website."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProductUpdate:
    """One concise, user-facing release entry."""

    published: str
    category: str
    title: str
    summary: str
    details: tuple[str, ...]
    commands: tuple[str, ...] = ()

    def as_public_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for the public updates API."""
        return asdict(self)


PRODUCT_UPDATES = (
    ProductUpdate(
        published="2026-07-16",
        category="Game dashboards",
        title="VALORANT and Minecraft become image-first",
        summary=(
            "Dense text embeds were replaced with rendered dashboards designed for "
            "fast scanning on desktop and mobile Discord."
        ),
        details=(
            "VALORANT now renders overview, match history, round timeline, personal economy, duel matrix, trends, and review-plan pages from official completed-match data.",
            "Match reviews use real map layouts, numbered kill/death positions, player-card or map banners, agent portraits, and finishing-weapon art loaded from a bounded public artwork cache.",
            "Round cards now resolve primary weapons and shields with current artwork and store metadata, then show damage received, damage differential, and recorded head/body/leg hits.",
            "The dashboard never estimates hidden MMR or ELO; every displayed metric is derived from a documented match field or clearly labelled aggregate.",
            "Minecraft PvP and inventory use cached in-game item sprites, remove unsupported display glyphs, preserve full-health golden apples, and acknowledge Discord before image rendering, audio, or reward writes.",
            "Fun commands share a consistent rendered-card system while preserving replay, scoring, elimination, and live-vote controls.",
        ),
        commands=(
            "/valorant stats",
            "/valorant match",
            "/valorant coach",
            "/minecraft pvp",
            "/minecraft inventory",
            "/fun coinflip",
            "/fun trivia",
        ),
    ),
    ProductUpdate(
        published="2026-07-16",
        category="Commands",
        title="Social, fun, and Minecraft sessions rebuilt",
        summary=(
            "Community commands now create richer sessions instead of sending "
            "single-use novelty responses."
        ),
        details=(
            "Welcome and wanted cards render at 1200 x 480 with themes, reactions, and private profile controls.",
            "Trivia, rock-paper-scissors, coin flips, dice, choices, and polls now support rendered cards, replay, scoring, or live voting.",
            "Minecraft rewards persist across restarts; the shop is transactional and PvP adds healing, surrender rewards, and optional voice effects.",
        ),
        commands=(
            "/social welcome",
            "/social wanted",
            "/fun trivia",
            "/fun rps",
            "/fun would-you-rather",
            "/minecraft pvp",
            "/minecraft shop",
            "/minecraft server",
        ),
    ),
    ProductUpdate(
        published="2026-07-16",
        category="Fixes",
        title="Moderation and custom-command startup fixes",
        summary=(
            "Two noisy or broken paths now fail safely and leave a clear audit trail."
        ),
        details=(
            "Purge no longer passes an invalid null callback to discord.py when no member filter is supplied.",
            "Legacy mixed-case custom-command names are normalized once in the database instead of warning on every startup.",
            "Built-in command name conflicts are skipped quietly while the stored server response remains intact.",
        ),
        commands=("purge", "customcommands", "addcommand", "removecommand"),
    ),
    ProductUpdate(
        published="2026-07-16",
        category="Platform",
        title="Cleaner command discovery",
        summary=(
            "Related commands are grouped under predictable slash-command namespaces."
        ),
        details=(
            "Minecraft actions now live under /minecraft instead of occupying unrelated global command slots.",
            "The command audit checks descriptions, usage metadata, duplicate registrations, and Discord's global command limit.",
            "Deployment metadata exposes the running version, branch, uptime, and a credential-free source commit link.",
        ),
    ),
)


def public_updates() -> list[dict[str, Any]]:
    """Return release entries ordered newest first."""
    return [update.as_public_dict() for update in PRODUCT_UPDATES]
