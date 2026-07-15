"""Modern, opt-in VALORANT commands backed by official Riot APIs."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp
import discord
from discord.ext import commands

LOGGER = logging.getLogger(__name__)
SUPPORTED_SHARDS = frozenset({"ap", "br", "eu", "kr", "latam", "na"})


class ValorantServiceError(RuntimeError):
    """Describe an expected website or Riot API failure to a command caller."""


@dataclass(frozen=True, slots=True)
class PlayerSummary:
    """Aggregate official match fields used by Discord presentation."""

    matches: int
    wins: int
    rounds: int
    kills: int
    deaths: int
    assists: int
    score: int
    damage: int
    headshots: int
    bodyshots: int
    legshots: int
    first_kills: int
    first_deaths: int
    agents: Counter[str]
    maps: Counter[str]
    ability_casts: int

    @property
    def win_rate(self) -> float:
        """Return wins as a percentage of analyzed matches."""
        return _ratio(self.wins * 100, self.matches)

    @property
    def kd_ratio(self) -> float:
        """Return kills per death without dividing by zero."""
        return _ratio(self.kills, self.deaths)

    @property
    def acs(self) -> float:
        """Return average combat score per played round."""
        return _ratio(self.score, self.rounds)

    @property
    def adr(self) -> float:
        """Return average damage per played round."""
        return _ratio(self.damage, self.rounds)

    @property
    def headshot_rate(self) -> float:
        """Return headshots as a percentage of recorded hit locations."""
        hits = self.headshots + self.bodyshots + self.legshots
        return _ratio(self.headshots * 100, hits)

    @property
    def opening_duel_rate(self) -> float:
        """Return won opening duels as a percentage of opening engagements."""
        return _ratio(self.first_kills * 100, self.first_kills + self.first_deaths)


class ValorantService:
    """Call Aestron's private integration API and Riot's official match API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        website_base_url: str | None,
        service_token: str | None,
        riot_api_key: str | None,
    ) -> None:
        """Configure private-site and official Riot request credentials."""
        self.session = session
        self.website_base_url = (website_base_url or "").rstrip("/")
        self.service_token = service_token or ""
        self.riot_api_key = riot_api_key or ""

    @property
    def linking_ready(self) -> bool:
        """Return whether the bot can securely call the deployed website."""
        return bool(self.website_base_url and self.service_token)

    @property
    def stats_ready(self) -> bool:
        """Return whether linking and official match retrieval are configured."""
        return self.linking_ready and bool(self.riot_api_key)

    async def create_link_url(self, discord_user_id: int) -> str:
        """Request a signed, expiring RSO URL for one Discord user."""
        payload = await self._site_request(
            "POST", "/api/v1/oauth/link", json={"discord_user_id": discord_user_id}
        )
        url = payload.get("authorization_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValorantServiceError("The linking service returned an invalid URL.")
        return url

    async def account(self, discord_user_id: int) -> dict[str, Any]:
        """Return one opted-in Riot identity from the private site API."""
        return await self._site_request(
            "GET", f"/api/v1/valorant/accounts/{discord_user_id}"
        )

    async def unlink(self, discord_user_id: int) -> None:
        """Delete one user's linked Riot identity and cached match references."""
        await self._site_request(
            "DELETE", f"/api/v1/valorant/accounts/{discord_user_id}", expect_json=False
        )

    async def recent_matches(
        self, account: dict[str, Any], *, limit: int = 8
    ) -> list[dict[str, Any]]:
        """Fetch recent official matches with bounded parallel requests."""
        puuid = str(account.get("puuid") or "")
        shard = str(account.get("region") or "").lower()
        if not puuid or shard not in SUPPORTED_SHARDS:
            raise ValorantServiceError(
                "The linked account has incomplete routing data. Please relink it."
            )
        history = await self._riot_request(
            shard,
            f"/val/match/v1/matchlists/by-puuid/{quote(puuid, safe='')}",
        )
        identifiers = [
            item.get("matchId")
            for item in history.get("history", [])[:limit]
            if isinstance(item, dict) and item.get("matchId")
        ]
        semaphore = asyncio.Semaphore(4)

        async def load(match_id: str) -> dict[str, Any] | None:
            async with semaphore:
                try:
                    return await self._riot_request(
                        shard,
                        f"/val/match/v1/matches/{quote(match_id, safe='')}",
                    )
                except ValorantServiceError:
                    LOGGER.exception("Could not fetch Riot match id=%s", match_id)
                    return None

        matches = await asyncio.gather(*(load(match_id) for match_id in identifiers))
        return [match for match in matches if match is not None]

    async def _site_request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        expect_json: bool = True,
    ) -> dict[str, Any]:
        if not self.linking_ready:
            raise ValorantServiceError(
                "VALORANT linking is not available until the Aestron website is deployed."
            )
        headers = {"X-Aestron-Service-Token": self.service_token}
        try:
            async with self.session.request(
                method,
                f"{self.website_base_url}{path}",
                headers=headers,
                json=json,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status == 204:
                    return {}
                payload = await response.json(content_type=None)
                if response.status == 404:
                    raise ValorantServiceError("No linked VALORANT account was found.")
                if response.status >= 400:
                    detail = payload.get("detail", "The Aestron API request failed.")
                    raise ValorantServiceError(str(detail))
                return payload if expect_json else {}
        except (aiohttp.ClientError, TimeoutError) as error:
            raise ValorantServiceError(
                "The Aestron linking service is temporarily unavailable."
            ) from error

    async def _riot_request(self, shard: str, path: str) -> dict[str, Any]:
        if not self.riot_api_key:
            raise ValorantServiceError("The Riot production API key is not configured.")
        headers = {"X-Riot-Token": self.riot_api_key}
        url = f"https://{shard}.api.riotgames.com{path}"
        for attempt in range(2):
            try:
                async with self.session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    if response.status == 429 and attempt == 0:
                        retry_after = min(
                            float(response.headers.get("Retry-After", 1)), 5
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    if response.status == 404:
                        raise ValorantServiceError("Riot could not find match data.")
                    if response.status in {401, 403}:
                        raise ValorantServiceError(
                            "Riot rejected the API credentials. The owner must renew them."
                        )
                    if response.status >= 400:
                        raise ValorantServiceError(
                            f"Riot's API returned HTTP {response.status}."
                        )
                    payload = await response.json(content_type=None)
                    if not isinstance(payload, dict):
                        raise ValorantServiceError("Riot returned an invalid response.")
                    return payload
            except (aiohttp.ClientError, TimeoutError) as error:
                raise ValorantServiceError(
                    "Riot's match service is temporarily unavailable."
                ) from error
        raise ValorantServiceError("Riot's rate limit is busy. Try again shortly.")


def summarize_matches(matches: list[dict[str, Any]], puuid: str) -> PlayerSummary:
    """Aggregate a player's official match fields without creating a skill rating."""
    values: Counter[str] = Counter()
    agents: Counter[str] = Counter()
    maps: Counter[str] = Counter()
    analyzed = 0
    for match in matches:
        players = match.get("players", [])
        player = next(
            (
                item
                for item in players
                if isinstance(item, dict) and item.get("puuid") == puuid
            ),
            None,
        )
        if player is None:
            continue
        stats = player.get("stats") or {}
        rounds = int(stats.get("roundsPlayed") or 0)
        if rounds <= 0:
            continue
        analyzed += 1
        for key in ("kills", "deaths", "assists", "score", "roundsPlayed"):
            values[key] += int(stats.get(key) or 0)
        ability_casts = stats.get("abilityCasts") or {}
        values["ability_casts"] += sum(
            int(ability_casts.get(key) or 0)
            for key in (
                "grenadeCasts",
                "ability1Casts",
                "ability2Casts",
                "ultimateCasts",
            )
        )
        character = str(player.get("characterId") or "Unknown agent")
        agents[character] += 1
        match_info = match.get("matchInfo") or {}
        maps[str(match_info.get("mapId") or "Unknown map")] += 1
        team_id = player.get("teamId")
        team = next(
            (
                item
                for item in match.get("teams", [])
                if isinstance(item, dict) and item.get("teamId") == team_id
            ),
            {},
        )
        values["wins"] += int(bool(team.get("won")))
        for round_result in match.get("roundResults", []):
            kills = [
                kill
                for item in round_result.get("playerStats", [])
                if isinstance(item, dict)
                for kill in item.get("kills", [])
                if isinstance(kill, dict)
            ]
            first_kill = min(
                kills,
                key=lambda item: item.get("timeSinceRoundStartMillis", 10**9),
                default=None,
            )
            if first_kill:
                values["first_kills"] += int(first_kill.get("killer") == puuid)
                values["first_deaths"] += int(first_kill.get("victim") == puuid)
            player_round = next(
                (
                    item
                    for item in round_result.get("playerStats", [])
                    if isinstance(item, dict) and item.get("puuid") == puuid
                ),
                {},
            )
            for damage in player_round.get("damage", []):
                values["damage"] += int(damage.get("damage") or 0)
                values["headshots"] += int(damage.get("headshots") or 0)
                values["bodyshots"] += int(damage.get("bodyshots") or 0)
                values["legshots"] += int(damage.get("legshots") or 0)
    return PlayerSummary(
        matches=analyzed,
        wins=values["wins"],
        rounds=values["roundsPlayed"],
        kills=values["kills"],
        deaths=values["deaths"],
        assists=values["assists"],
        score=values["score"],
        damage=values["damage"],
        headshots=values["headshots"],
        bodyshots=values["bodyshots"],
        legshots=values["legshots"],
        first_kills=values["first_kills"],
        first_deaths=values["first_deaths"],
        agents=agents,
        maps=maps,
        ability_casts=values["ability_casts"],
    )


def coaching_notes(summary: PlayerSummary) -> list[str]:
    """Produce transparent review prompts from the displayed aggregates."""
    if summary.matches == 0:
        return ["Play a supported match, then run this command again."]
    notes: list[str] = []
    if summary.first_kills + summary.first_deaths >= 3:
        if summary.opening_duel_rate < 45:
            notes.append(
                f"Opening duels: {summary.first_kills} first kills vs "
                f"{summary.first_deaths} first deaths. Review positioning and utility "
                "on the rounds where you were the first death."
            )
        else:
            notes.append(
                f"Opening duels are converting at {summary.opening_duel_rate:.0f}%. "
                "Review whether your team could trade or build on those advantages."
            )
    if summary.adr < 110:
        notes.append(
            f"Damage impact averaged {summary.adr:.0f} ADR. Review crossfire timing "
            "and whether utility created damage opportunities before each duel."
        )
    elif summary.adr >= 150:
        notes.append(
            f"Damage impact is strong at {summary.adr:.0f} ADR. Check how often that "
            "damage converted into round wins rather than chasing a higher number."
        )
    casts_per_round = _ratio(summary.ability_casts, summary.rounds)
    notes.append(
        f"Utility usage averaged {casts_per_round:.1f} casts per round. Compare deaths "
        "with unused utility; the number itself is context, not a target."
    )
    return notes[:3]


def stats_overview_embed(
    account: dict[str, Any], summary: PlayerSummary
) -> discord.Embed:
    """Build the interactive VALORANT overview card."""
    embed = discord.Embed(
        title=f"{account['accountname']}#{account['accounttag']} · recent form",
        description=(
            f"Official post-match data from **{summary.matches} matches** and "
            f"**{summary.rounds} rounds**. This is not a replacement rank."
        ),
        color=discord.Color.red(),
    )
    embed.add_field(
        name="Record",
        value=f"{summary.wins}W · {summary.win_rate:.1f}%",
        inline=True,
    )
    embed.add_field(
        name="K / D / A",
        value=(
            f"{summary.kills} / {summary.deaths} / {summary.assists}\n"
            f"K/D {summary.kd_ratio:.2f}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Impact",
        value=f"ACS {summary.acs:.0f}\nADR {summary.adr:.0f}",
        inline=True,
    )
    embed.add_field(
        name="Headshot hits", value=f"{summary.headshot_rate:.1f}%", inline=True
    )
    embed.add_field(
        name="Opening duels",
        value=f"{summary.first_kills} won · {summary.first_deaths} lost",
        inline=True,
    )
    embed.set_footer(text="Opt-in Riot data • Use the controls below for context")
    return embed


def coaching_embed(account: dict[str, Any], summary: PlayerSummary) -> discord.Embed:
    """Build transparent post-match review prompts."""
    notes = coaching_notes(summary)
    embed = discord.Embed(
        title=f"Review plan · {account['accountname']}#{account['accounttag']}",
        description="\n\n".join(
            f"**{index}.** {note}" for index, note in enumerate(notes, start=1)
        ),
        color=discord.Color.orange(),
    )
    embed.set_footer(text="Post-match reflection only • no live tactical advice")
    return embed


def metrics_guide_embed(account: dict[str, Any]) -> discord.Embed:
    """Explain the aggregates without implying a hidden skill score."""
    embed = discord.Embed(
        title=f"Metrics guide · {account['accountname']}#{account['accounttag']}",
        description=(
            "These numbers summarize completed matches. Context such as role, "
            "economy, team plan, and opponent strength still matters."
        ),
        color=0x7C5CFC,
    )
    embed.add_field(
        name="ACS / ADR",
        value="Combat score and damage averaged across played rounds.",
        inline=False,
    )
    embed.add_field(
        name="Headshot hits",
        value="Headshots as a share of recorded head, body, and leg hits.",
        inline=False,
    )
    embed.add_field(
        name="Opening duels",
        value="Rounds where this player made or received the first kill.",
        inline=False,
    )
    embed.add_field(
        name="Review prompts",
        value="Rule-based observations from displayed aggregates—not AI rank or MMR.",
        inline=False,
    )
    return embed


class ValorantStatsView(discord.ui.View):
    """Interactive overview, coaching, and metric explanations."""

    def __init__(
        self,
        *,
        author_id: int,
        account: dict[str, Any],
        summary: PlayerSummary,
        initial_page: str = "overview",
    ) -> None:
        """Create a stats panel restricted to the invoking Discord user."""
        super().__init__(timeout=180)
        self.author_id = author_id
        self.account = account
        self.summary = summary
        self.current_page = initial_page
        self.message: discord.Message | None = None
        self._refresh_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Prevent other members from replacing the caller's private panel."""
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Run this command yourself to inspect a VALORANT profile.", ephemeral=True
        )
        return False

    def render(self) -> discord.Embed:
        """Render the active stats page."""
        if self.current_page == "coaching":
            return coaching_embed(self.account, self.summary)
        if self.current_page == "metrics":
            return metrics_guide_embed(self.account)
        return stats_overview_embed(self.account, self.summary)

    def _refresh_buttons(self) -> None:
        self.overview_button.disabled = self.current_page == "overview"
        self.coaching_button.disabled = self.current_page == "coaching"
        self.metrics_button.disabled = self.current_page == "metrics"

    async def _show(self, interaction: discord.Interaction, page: str) -> None:
        self.current_page = page
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(
        label="Overview", emoji="📊", style=discord.ButtonStyle.secondary
    )
    async def overview_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Show recent aggregate performance."""
        await self._show(interaction, "overview")

    @discord.ui.button(
        label="Review plan", emoji="🎯", style=discord.ButtonStyle.primary
    )
    async def coaching_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Show post-match coaching prompts."""
        await self._show(interaction, "coaching")

    @discord.ui.button(
        label="Metrics guide", emoji="ℹ️", style=discord.ButtonStyle.secondary
    )
    async def metrics_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Explain displayed values and their limits."""
        await self._show(interaction, "metrics")

    async def on_timeout(self) -> None:
        """Disable expired controls while preserving the displayed data."""
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Valorant(commands.Cog):
    """Opt-in VALORANT match summaries and post-match review tools."""

    def __init__(self, bot: commands.Bot) -> None:
        """Create the command service from the bot's validated settings."""
        self.bot = bot
        self.service: ValorantService | None = None

    def _service(self) -> ValorantService:
        """Create the HTTP service lazily after the bot session is ready."""
        session = getattr(self.bot, "session", None)
        if session is None or session.closed:
            raise ValorantServiceError("Aestron's HTTP service is not ready yet.")
        if self.service is not None and self.service.session is session:
            return self.service
        self.service = ValorantService(
            session,
            website_base_url=getattr(self.bot, "aestron_site_base_url", None),
            service_token=getattr(self.bot, "aestron_service_token", None),
            riot_api_key=getattr(self.bot, "valorant_api_key", None),
        )
        return self.service

    async def _load(
        self, ctx: commands.Context, member: discord.Member | discord.User
    ) -> tuple[dict[str, Any], PlayerSummary] | None:
        try:
            service = self._service()
            account = await service.account(member.id)
            matches = await service.recent_matches(account)
            summary = summarize_matches(matches, str(account["puuid"]))
            return account, summary
        except ValorantServiceError as error:
            await ctx.send(f"⚠️ {error}", ephemeral=True)
            return None

    @commands.hybrid_command(
        aliases=["vallink"],
        brief="Securely link your Riot account.",
        description="Creates a private, expiring Riot Sign On link for your Discord account.",
        usage="",
    )
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def linkaccount(self, ctx: commands.Context) -> None:
        """Create a secure Riot Sign On URL for the invoking user."""
        try:
            url = await self._service().create_link_url(ctx.author.id)
        except ValorantServiceError as error:
            await ctx.send(f"⚠️ {error}", ephemeral=True)
            return
        view = discord.ui.View(timeout=600)
        view.add_item(discord.ui.Button(label="Continue to Riot", url=url))
        await ctx.send(
            "Riot will ask you to authorize Aestron. The link expires in 10 minutes. "
            "Linking opts your authorized VALORANT identity and match statistics into "
            "Aestron's bot and website; you can unlink at any time.",
            view=view,
            ephemeral=True,
        )

    @commands.hybrid_command(
        aliases=["valunlink"],
        brief="Unlink your Riot account and cached data.",
        description="Removes your linked Riot identity and cached match references.",
        usage="",
    )
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def unlinkaccount(self, ctx: commands.Context) -> None:
        """Delete the invoking user's opt-in Riot link."""
        try:
            await self._service().unlink(ctx.author.id)
        except ValorantServiceError as error:
            await ctx.send(f"⚠️ {error}", ephemeral=True)
            return
        await ctx.send(
            "Your Riot account link and cached data were removed.", ephemeral=True
        )

    @commands.hybrid_command(
        aliases=["valstats"],
        brief="Show recent official VALORANT performance stats.",
        description="Summarizes up to eight recent matches for an opted-in player.",
        usage="[member]",
    )
    @commands.cooldown(1, 20, commands.BucketType.user)
    async def vstats(
        self,
        ctx: commands.Context,
        member: discord.Member | discord.User | None = None,
    ) -> None:
        """Show a compact recent-match summary for an opted-in player."""
        target = member or ctx.author
        await ctx.defer(ephemeral=True)
        loaded = await self._load(ctx, target)
        if loaded is None:
            return
        account, summary = loaded
        view = ValorantStatsView(
            author_id=ctx.author.id,
            account=account,
            summary=summary,
        )
        view.message = await ctx.send(embed=view.render(), view=view, ephemeral=True)

    @commands.hybrid_command(
        brief="Turn recent VALORANT stats into review prompts.",
        description="Shows evidence-based post-match practice ideas for an opted-in player.",
        usage="[member]",
    )
    @commands.cooldown(1, 20, commands.BucketType.user)
    async def valcoach(
        self,
        ctx: commands.Context,
        member: discord.Member | discord.User | None = None,
    ) -> None:
        """Show transparent post-match coaching prompts."""
        target = member or ctx.author
        await ctx.defer(ephemeral=True)
        loaded = await self._load(ctx, target)
        if loaded is None:
            return
        account, summary = loaded
        view = ValorantStatsView(
            author_id=ctx.author.id,
            account=account,
            summary=summary,
            initial_page="coaching",
        )
        view.message = await ctx.send(embed=view.render(), view=view, ephemeral=True)


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0
