"""Pure VALORANT match analytics built from Riot's official completed-match DTOs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True, slots=True)
class AssetCatalog:
    """Resolve Riot content identifiers to current localized display names."""

    agents: dict[str, str]
    maps: dict[str, str]

    @classmethod
    def from_riot_content(cls, payload: dict[str, Any]) -> AssetCatalog:
        """Build case-insensitive lookups from VAL-CONTENT-V1 data."""

        def build(items: Any) -> dict[str, str]:
            names: dict[str, str] = {}
            if not isinstance(items, list):
                return names
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                for key in ("id", "assetName", "assetPath"):
                    identifier = str(item.get(key) or "").strip().casefold()
                    if identifier:
                        names[identifier] = name
            return names

        return cls(
            agents=build(payload.get("characters")),
            maps=build(payload.get("maps")),
        )

    def agent_name(self, identifier: Any) -> str:
        """Return a current agent name or a readable fallback identifier."""
        return self._resolve(self.agents, identifier, "Unknown agent")

    def map_name(self, identifier: Any) -> str:
        """Return a current map name or a readable fallback identifier."""
        return self._resolve(self.maps, identifier, "Unknown map")

    @staticmethod
    def _resolve(mapping: dict[str, str], value: Any, fallback: str) -> str:
        identifier = str(value or "").strip()
        if not identifier:
            return fallback
        resolved = mapping.get(identifier.casefold())
        if resolved:
            return resolved
        if "/" in identifier:
            candidate = identifier.rstrip("/").rsplit("/", maxsplit=1)[-1]
            if candidate:
                return candidate.replace("_", " ")
        return identifier if len(identifier) <= 32 else fallback


EMPTY_CATALOG = AssetCatalog(agents={}, maps={})


@dataclass(frozen=True, slots=True)
class MatchPerformance:
    """One player's transparent performance metrics for one completed match."""

    match_id: str
    game_start_millis: int
    queue: str
    map_name: str
    agent_name: str
    won: bool
    rounds: int
    rounds_won: int
    rounds_lost: int
    kills: int
    deaths: int
    assists: int
    score: int
    damage: int
    damage_received: int
    headshots: int
    bodyshots: int
    legshots: int
    first_kills: int
    first_deaths: int
    survival_rounds: int
    multi_kill_rounds: int
    plants: int
    defuses: int
    ability_casts: int

    @property
    def kd_ratio(self) -> float:
        """Return kills divided by deaths."""
        return _ratio(self.kills, self.deaths)

    @property
    def kda_ratio(self) -> float:
        """Return kills plus assists divided by deaths."""
        return _ratio(self.kills + self.assists, self.deaths)

    @property
    def acs(self) -> float:
        """Return average combat score per round."""
        return _ratio(self.score, self.rounds)

    @property
    def adr(self) -> float:
        """Return average damage dealt per round."""
        return _ratio(self.damage, self.rounds)

    @property
    def damage_delta(self) -> float:
        """Return net damage dealt per round."""
        return _ratio(self.damage - self.damage_received, self.rounds)

    @property
    def headshot_rate(self) -> float:
        """Return headshots as a percentage of recorded hits."""
        hits = self.headshots + self.bodyshots + self.legshots
        return _ratio(self.headshots * 100, hits)

    @property
    def survival_rate(self) -> float:
        """Return the percentage of rounds survived."""
        return _ratio(self.survival_rounds * 100, self.rounds)

    @property
    def scoreline(self) -> str:
        """Return the match round score when it is available."""
        if self.rounds_won or self.rounds_lost:
            return f"{self.rounds_won}-{self.rounds_lost}"
        return "Win" if self.won else "Loss"


@dataclass(frozen=True, slots=True)
class PlayerSummary:
    """Aggregate official fields plus ordered match-level performances."""

    matches: int
    wins: int
    rounds: int
    kills: int
    deaths: int
    assists: int
    score: int
    damage: int
    damage_received: int
    headshots: int
    bodyshots: int
    legshots: int
    first_kills: int
    first_deaths: int
    survival_rounds: int
    multi_kill_rounds: int
    plants: int
    defuses: int
    agents: Counter[str]
    maps: Counter[str]
    ability_casts: int
    performances: tuple[MatchPerformance, ...]

    @property
    def losses(self) -> int:
        """Return matches not recorded as wins."""
        return max(0, self.matches - self.wins)

    @property
    def win_rate(self) -> float:
        """Return wins as a percentage of analyzed matches."""
        return _ratio(self.wins * 100, self.matches)

    @property
    def kd_ratio(self) -> float:
        """Return aggregate kills divided by deaths."""
        return _ratio(self.kills, self.deaths)

    @property
    def kda_ratio(self) -> float:
        """Return aggregate kills plus assists divided by deaths."""
        return _ratio(self.kills + self.assists, self.deaths)

    @property
    def acs(self) -> float:
        """Return aggregate average combat score per round."""
        return _ratio(self.score, self.rounds)

    @property
    def adr(self) -> float:
        """Return aggregate average damage dealt per round."""
        return _ratio(self.damage, self.rounds)

    @property
    def damage_delta(self) -> float:
        """Return aggregate net damage dealt per round."""
        return _ratio(self.damage - self.damage_received, self.rounds)

    @property
    def headshot_rate(self) -> float:
        """Return aggregate headshot percentage."""
        hits = self.headshots + self.bodyshots + self.legshots
        return _ratio(self.headshots * 100, hits)

    @property
    def opening_duel_rate(self) -> float:
        """Return won opening duels as a percentage of opening duels."""
        return _ratio(self.first_kills * 100, self.first_kills + self.first_deaths)

    @property
    def survival_rate(self) -> float:
        """Return the aggregate percentage of rounds survived."""
        return _ratio(self.survival_rounds * 100, self.rounds)

    @property
    def casts_per_round(self) -> float:
        """Return recorded ability casts per round."""
        return _ratio(self.ability_casts, self.rounds)


def analyze_match(
    match: dict[str, Any],
    puuid: str,
    catalog: AssetCatalog = EMPTY_CATALOG,
) -> MatchPerformance | None:
    """Extract one player's match and round impact without inventing hidden data."""
    players = match.get("players") or []
    player = next(
        (
            item
            for item in players
            if isinstance(item, dict) and item.get("puuid") == puuid
        ),
        None,
    )
    if player is None:
        return None

    stats = player.get("stats") or {}
    round_results = [
        item for item in (match.get("roundResults") or []) if isinstance(item, dict)
    ]
    rounds = _integer(stats.get("roundsPlayed")) or len(round_results)
    if rounds <= 0:
        return None

    values: Counter[str] = Counter()
    for round_result in round_results:
        player_stats = [
            item
            for item in (round_result.get("playerStats") or [])
            if isinstance(item, dict)
        ]
        all_kills = [
            kill
            for item in player_stats
            for kill in (item.get("kills") or [])
            if isinstance(kill, dict)
        ]
        first_kill = min(
            all_kills,
            key=lambda item: _integer(item.get("timeSinceRoundStartMillis")) or 10**9,
            default=None,
        )
        if first_kill:
            values["first_kills"] += int(first_kill.get("killer") == puuid)
            values["first_deaths"] += int(first_kill.get("victim") == puuid)

        player_kills = [kill for kill in all_kills if kill.get("killer") == puuid]
        values["multi_kill_rounds"] += int(len(player_kills) >= 2)
        values["survival_rounds"] += int(
            not any(kill.get("victim") == puuid for kill in all_kills)
        )
        values["plants"] += int(round_result.get("bombPlanter") == puuid)
        values["defuses"] += int(round_result.get("bombDefuser") == puuid)

        player_round = next(
            (item for item in player_stats if item.get("puuid") == puuid), {}
        )
        for damage in player_round.get("damage") or []:
            if not isinstance(damage, dict):
                continue
            values["damage"] += _integer(damage.get("damage"))
            values["headshots"] += _integer(damage.get("headshots"))
            values["bodyshots"] += _integer(damage.get("bodyshots"))
            values["legshots"] += _integer(damage.get("legshots"))

        for item in player_stats:
            for damage in item.get("damage") or []:
                if isinstance(damage, dict) and damage.get("receiver") == puuid:
                    values["damage_received"] += _integer(damage.get("damage"))

    ability_casts = stats.get("abilityCasts") or {}
    ability_total = sum(
        _integer(ability_casts.get(key))
        for key in (
            "grenadeCasts",
            "ability1Casts",
            "ability2Casts",
            "ultimateCasts",
        )
    )
    team_id = player.get("teamId")
    teams = [item for item in (match.get("teams") or []) if isinstance(item, dict)]
    team = next((item for item in teams if item.get("teamId") == team_id), {})
    opponent = next((item for item in teams if item.get("teamId") != team_id), {})
    match_info = match.get("matchInfo") or {}

    return MatchPerformance(
        match_id=str(match_info.get("matchId") or "Unknown match"),
        game_start_millis=_integer(match_info.get("gameStartMillis")),
        queue=str(match_info.get("queueId") or "Unknown queue").replace("_", " "),
        map_name=catalog.map_name(match_info.get("mapId")),
        agent_name=catalog.agent_name(player.get("characterId")),
        won=bool(team.get("won")),
        rounds=rounds,
        rounds_won=_integer(team.get("roundsWon")),
        rounds_lost=_integer(opponent.get("roundsWon")),
        kills=_integer(stats.get("kills")),
        deaths=_integer(stats.get("deaths")),
        assists=_integer(stats.get("assists")),
        score=_integer(stats.get("score")),
        damage=values["damage"],
        damage_received=values["damage_received"],
        headshots=values["headshots"],
        bodyshots=values["bodyshots"],
        legshots=values["legshots"],
        first_kills=values["first_kills"],
        first_deaths=values["first_deaths"],
        survival_rounds=values["survival_rounds"],
        multi_kill_rounds=values["multi_kill_rounds"],
        plants=values["plants"],
        defuses=values["defuses"],
        ability_casts=ability_total,
    )


def summarize_matches(
    matches: list[dict[str, Any]],
    puuid: str,
    catalog: AssetCatalog = EMPTY_CATALOG,
) -> PlayerSummary:
    """Aggregate match performances in Riot's recent-history order."""
    performances = tuple(
        performance
        for match in matches
        if (performance := analyze_match(match, puuid, catalog)) is not None
    )
    values: Counter[str] = Counter()
    agents: Counter[str] = Counter()
    maps: Counter[str] = Counter()
    for performance in performances:
        values.update(
            {
                "wins": int(performance.won),
                "rounds": performance.rounds,
                "kills": performance.kills,
                "deaths": performance.deaths,
                "assists": performance.assists,
                "score": performance.score,
                "damage": performance.damage,
                "damage_received": performance.damage_received,
                "headshots": performance.headshots,
                "bodyshots": performance.bodyshots,
                "legshots": performance.legshots,
                "first_kills": performance.first_kills,
                "first_deaths": performance.first_deaths,
                "survival_rounds": performance.survival_rounds,
                "multi_kill_rounds": performance.multi_kill_rounds,
                "plants": performance.plants,
                "defuses": performance.defuses,
                "ability_casts": performance.ability_casts,
            }
        )
        agents[performance.agent_name] += 1
        maps[performance.map_name] += 1

    return PlayerSummary(
        matches=len(performances),
        wins=values["wins"],
        rounds=values["rounds"],
        kills=values["kills"],
        deaths=values["deaths"],
        assists=values["assists"],
        score=values["score"],
        damage=values["damage"],
        damage_received=values["damage_received"],
        headshots=values["headshots"],
        bodyshots=values["bodyshots"],
        legshots=values["legshots"],
        first_kills=values["first_kills"],
        first_deaths=values["first_deaths"],
        survival_rounds=values["survival_rounds"],
        multi_kill_rounds=values["multi_kill_rounds"],
        plants=values["plants"],
        defuses=values["defuses"],
        agents=agents,
        maps=maps,
        ability_casts=values["ability_casts"],
        performances=performances,
    )


def coaching_notes(summary: PlayerSummary) -> list[str]:
    """Produce transparent post-match review prompts from displayed evidence."""
    if summary.matches == 0:
        return ["Play a supported match, then run this command again."]

    notes: list[str] = []
    opening_duels = summary.first_kills + summary.first_deaths
    if opening_duels >= 3:
        if summary.opening_duel_rate < 45:
            notes.append(
                f"You went {summary.first_kills}-{summary.first_deaths} in opening "
                "duels. Review the first-death rounds for isolated peeks, missing "
                "trade spacing, or utility that could have preceded contact."
            )
        else:
            notes.append(
                f"Your opening duel conversion was {summary.opening_duel_rate:.0f}%. "
                "Review whether those advantages became site control or round wins."
            )

    if summary.adr < 110:
        notes.append(
            f"Impact averaged {summary.adr:.0f} ADR. Review crosshair readiness, "
            "trade timing, and whether utility created a favorable first fight."
        )
    elif summary.adr >= 150:
        notes.append(
            f"Damage output was strong at {summary.adr:.0f} ADR. Check whether chip "
            "damage converted into eliminations, space, saves, or round wins."
        )

    if summary.damage_received:
        direction = "positive" if summary.damage_delta >= 0 else "negative"
        notes.append(
            f"Damage delta was {summary.damage_delta:+.0f} per round ({direction}). "
            "Review low-delta rounds for avoidable exposure and untraded damage."
        )

    if summary.survival_rate < 30 and summary.first_deaths > summary.first_kills:
        notes.append(
            f"You survived {summary.survival_rate:.0f}% of rounds while losing more "
            "openers than you won. Prioritize tradable paths and a clear escape plan."
        )

    notes.append(
        f"Utility averaged {summary.casts_per_round:.1f} casts per round. Compare "
        "deaths with unused utility; cast count is context, not a target score."
    )
    return notes[:4]
