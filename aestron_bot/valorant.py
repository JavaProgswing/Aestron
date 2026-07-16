"""Opt-in VALORANT commands backed by official Riot APIs."""

from __future__ import annotations

import asyncio
import logging
import time
from io import BytesIO
from typing import Any
from urllib.parse import quote

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from .valorant_analytics import (
    AssetCatalog,
    MatchPerformance,
    PlayerSummary,
    summarize_matches,
)
from .valorant_assets import ValorantArtwork, ValorantAssetService
from .valorant_ui import render_valorant_dashboard

LOGGER = logging.getLogger(__name__)
SUPPORTED_SHARDS = frozenset({"ap", "br", "eu", "kr", "latam", "na"})


class ValorantServiceError(RuntimeError):
    """Describe an expected website or Riot API failure to a command caller."""


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
        self._match_cache: dict[
            tuple[str, str], tuple[float, tuple[dict[str, Any], ...]]
        ] = {}
        self._catalog_cache: dict[str, tuple[float, AssetCatalog]] = {}
        self._cache_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self.asset_service = ValorantAssetService(session)

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
        """Fetch and briefly cache recent matches with bounded parallel requests."""
        puuid = str(account.get("puuid") or "")
        shard = str(account.get("region") or "").lower()
        if not puuid or shard not in SUPPORTED_SHARDS:
            raise ValorantServiceError(
                "The linked account has incomplete routing data. Please relink it."
            )
        limit = max(1, min(10, limit))
        cache_key = (shard, puuid)
        cached = self._match_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 120:
            return list(cached[1][:limit])

        lock = self._cache_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = self._match_cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < 120:
                return list(cached[1][:limit])

            history = await self._riot_request(
                shard,
                f"/val/match/v1/matchlists/by-puuid/{quote(puuid, safe='')}",
            )
            identifiers = [
                str(item["matchId"])
                for item in history.get("history", [])[:10]
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
                    except ValorantServiceError as error:
                        LOGGER.warning(
                            "Could not fetch Riot match id=%s: %s", match_id, error
                        )
                        return None

            loaded = await asyncio.gather(*(load(match_id) for match_id in identifiers))
            matches = tuple(match for match in loaded if match is not None)
            if identifiers and not matches:
                raise ValorantServiceError(
                    "Riot returned match history but every match detail failed to load."
                )
            self._match_cache[cache_key] = (time.monotonic(), matches)
            return list(matches[:limit])

    async def content_catalog(self, account: dict[str, Any]) -> AssetCatalog:
        """Return a six-hour cache of current Riot agent and map names."""
        shard = str(account.get("region") or "").lower()
        if shard not in SUPPORTED_SHARDS:
            return AssetCatalog(agents={}, maps={})
        cached = self._catalog_cache.get(shard)
        if cached and time.monotonic() - cached[0] < 21_600:
            return cached[1]
        try:
            payload = await self._riot_request(
                shard, "/val/content/v1/contents?locale=en-US"
            )
        except ValorantServiceError as error:
            LOGGER.warning("Could not refresh Riot content catalog: %s", error)
            return AssetCatalog(agents={}, maps={})
        catalog = AssetCatalog.from_riot_content(payload)
        self._catalog_cache[shard] = (time.monotonic(), catalog)
        return catalog

    async def artwork(self, summary: PlayerSummary) -> ValorantArtwork:
        """Fetch cached public artwork required by the rendered dashboard."""
        return await self.asset_service.load(summary)

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
                        try:
                            retry_after = min(
                                max(float(response.headers.get("Retry-After", 1)), 0),
                                5,
                            )
                        except ValueError:
                            retry_after = 1
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


class MatchSelect(discord.ui.Select):
    """Select one recent match without issuing another Riot request."""

    def __init__(self, summary: PlayerSummary) -> None:
        """Create options for each analyzed recent match."""
        options = [
            discord.SelectOption(
                label=f"{index}. {'Win' if match.won else 'Loss'} · {match.map_name}"[
                    :100
                ],
                description=(
                    f"{match.agent_name} · {match.kills}/{match.deaths}/{match.assists} · "
                    f"{match.acs:.0f} ACS"
                )[:100],
                value=str(index - 1),
            )
            for index, match in enumerate(summary.performances, start=1)
        ]
        super().__init__(
            placeholder="Inspect a recent match…",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open the selected match detail page."""
        view = self.view
        if not isinstance(view, ValorantStatsView):
            return
        await view._show(interaction, f"match:{self.values[0]}")


class MatchSectionSelect(discord.ui.Select):
    """Switch between summary, round, economy, and duel views for one match."""

    def __init__(self, *, disabled: bool) -> None:
        """Create the match lens selector, disabled until a match is chosen."""
        super().__init__(
            placeholder="Choose a match detail lens…",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Match summary", value="summary"),
                discord.SelectOption(label="Round timeline", value="rounds"),
                discord.SelectOption(label="Economy review", value="economy"),
                discord.SelectOption(label="Duel matrix", value="duels"),
            ],
            disabled=disabled,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open the selected lens for the active match."""
        view = self.view
        if not isinstance(view, ValorantStatsView):
            return
        index = view.selected_match_index
        if index is None:
            await interaction.response.send_message(
                "Select a match first.", ephemeral=True
            )
            return
        await view._show(interaction, f"match:{index}:{self.values[0]}")


class RoundSelect(discord.ui.Select):
    """Open one round's spatial and economy review from the selected match."""

    def __init__(self, *, disabled: bool = True) -> None:
        """Create a round picker that is populated when a match is selected."""
        super().__init__(
            placeholder="Choose a round for the map replay…",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label="Select a match first", value="0")],
            disabled=disabled,
            row=3,
        )

    def configure(self, match: MatchPerformance | None) -> None:
        """Replace stale options with the selected match's available rounds."""
        if match is None or not match.round_details:
            self.options = [
                discord.SelectOption(label="Round data unavailable", value="0")
            ]
            self.disabled = True
            return
        self.options = [
            discord.SelectOption(
                label=f"Round {detail.number:02} · "
                f"{'Win' if detail.won else 'Loss' if detail.won is False else 'Result'}",
                description=(
                    f"{detail.kills}/{detail.deaths}/{detail.assists} · "
                    f"{detail.damage} damage · {detail.loadout_value:,} loadout"
                )[:100],
                # Prefixing the display number with its stable list position
                # keeps Discord values unique even if an upstream payload is
                # malformed or repeats a round index.
                value=f"{position}:{detail.number}",
            )
            for position, detail in enumerate(match.round_details[:25], start=1)
        ]
        self.disabled = False

    async def callback(self, interaction: discord.Interaction) -> None:
        """Render the chosen round after immediately acknowledging Discord."""
        view = self.view
        if not isinstance(view, ValorantStatsView):
            return
        index = view.selected_match_index
        if index is None:
            await interaction.response.send_message(
                "Select a match first.", ephemeral=True
            )
            return
        round_number = self.values[0].rsplit(":", maxsplit=1)[-1]
        await view._show(interaction, f"match:{index}:round:{round_number}")


class ValorantStatsView(discord.ui.View):
    """Interactive overview, history, match drill-down, coaching, and guides."""

    def __init__(
        self,
        *,
        author_id: int,
        account: dict[str, Any],
        summary: PlayerSummary,
        artwork: ValorantArtwork | None = None,
        initial_page: str = "overview",
    ) -> None:
        """Create a stats panel restricted to the invoking Discord user."""
        super().__init__(timeout=180)
        self.author_id = author_id
        self.account = account
        self.summary = summary
        self.artwork = artwork or ValorantArtwork()
        self.current_page = initial_page
        self.selected_match_index: int | None = (
            int(initial_page.split(":")[1])
            if initial_page.startswith("match:")
            else None
        )
        self.message: discord.Message | None = None
        if summary.performances:
            self.add_item(MatchSelect(summary))
        self.section_select = MatchSectionSelect(
            disabled=self.selected_match_index is None
        )
        self.add_item(self.section_select)
        self.round_select = RoundSelect()
        self.add_item(self.round_select)
        if self.selected_match_index is not None:
            self.round_select.configure(
                self.summary.performances[self.selected_match_index]
            )
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
        """Render a minimal Discord frame around the image-first dashboard."""
        labels = {
            "overview": "Performance overview",
            "matches": "Recent match history",
            "breakdown": "Agent, map, and form trends",
            "coaching": "Post-match review plan",
            "metrics": "Dashboard metric guide",
        }
        title = labels.get(self.current_page, "Completed match review")
        if self.current_page.startswith("match:"):
            parts = self.current_page.split(":")
            if len(parts) == 4 and parts[2] == "round":
                title = f"Match review · Round {parts[3]}"
            else:
                section = parts[-1]
                if section.isdigit():
                    section = "summary"
                title = f"Match review · {section.title()}"
        embed = discord.Embed(
            title=title,
            description="Use the controls below to change the rendered dashboard.",
            color=0xFF4655,
        )
        embed.set_image(url="attachment://valorant-dashboard.png")
        embed.set_footer(
            text="Official completed-match data · opt-in only · no MMR estimate"
        )
        return embed

    def render_image(self) -> bytes:
        """Render the current page as an information-dense dashboard image."""
        return render_valorant_dashboard(
            self.account,
            self.summary,
            page=self.current_page,
            artwork=self.artwork,
        )

    async def send(self, ctx: commands.Context) -> discord.Message:
        """Render and send the initial private dashboard."""
        image = await asyncio.to_thread(self.render_image)
        self.message = await ctx.send(
            embed=self.render(),
            view=self,
            file=discord.File(BytesIO(image), filename="valorant-dashboard.png"),
            ephemeral=True,
        )
        return self.message

    def _refresh_buttons(self) -> None:
        self.overview_button.disabled = self.current_page == "overview"
        self.matches_button.disabled = self.current_page == "matches"
        self.breakdown_button.disabled = self.current_page == "breakdown"
        self.coaching_button.disabled = self.current_page == "coaching"
        self.metrics_button.disabled = self.current_page == "metrics"

    async def _show(self, interaction: discord.Interaction, page: str) -> None:
        await interaction.response.defer()
        self.current_page = page
        if page.startswith("match:"):
            self.selected_match_index = int(page.split(":")[1])
        self.section_select.disabled = self.selected_match_index is None
        selected_match = (
            self.summary.performances[self.selected_match_index]
            if self.selected_match_index is not None
            else None
        )
        self.round_select.configure(selected_match)
        self._refresh_buttons()
        image = await asyncio.to_thread(self.render_image)
        message = interaction.message or self.message
        if message is not None:
            await message.edit(
                embed=self.render(),
                view=self,
                attachments=[
                    discord.File(BytesIO(image), filename="valorant-dashboard.png")
                ],
            )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        """Report a safe private error after logging dashboard failures."""
        LOGGER.exception(
            "VALORANT dashboard failed custom_id=%s",
            getattr(item, "custom_id", None),
            exc_info=error,
        )
        message = "That dashboard view failed to render. Your match data is unchanged."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(label="Overview", style=discord.ButtonStyle.secondary)
    async def overview_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Show recent aggregate performance."""
        await self._show(interaction, "overview")

    @discord.ui.button(label="Matches", style=discord.ButtonStyle.secondary)
    async def matches_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Show recent match cards."""
        await self._show(interaction, "matches")

    @discord.ui.button(label="Trends", style=discord.ButtonStyle.secondary)
    async def breakdown_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Show agent, map, and recent-form context."""
        await self._show(interaction, "breakdown")

    @discord.ui.button(label="Review", style=discord.ButtonStyle.primary)
    async def coaching_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Show post-match coaching prompts."""
        await self._show(interaction, "coaching")

    @discord.ui.button(label="Guide", style=discord.ButtonStyle.secondary)
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

    valorant = app_commands.Group(
        name="valorant", description="Link Riot and analyze VALORANT performance."
    )

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
        self,
        ctx: commands.Context,
        member: discord.Member | discord.User,
        *,
        limit: int = 8,
    ) -> tuple[dict[str, Any], PlayerSummary, ValorantArtwork] | None:
        try:
            service = self._service()
            account = await service.account(member.id)
            matches, catalog = await asyncio.gather(
                service.recent_matches(account, limit=limit),
                service.content_catalog(account),
            )
            summary = summarize_matches(matches, str(account["puuid"]), catalog=catalog)
            artwork = await service.artwork(summary)
            return account, summary, artwork
        except ValorantServiceError as error:
            await ctx.send(f"⚠️ {error}", ephemeral=True)
            return None

    @commands.hybrid_command(
        name="vallink",
        with_app_command=False,
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
        view.add_item(
            discord.ui.Button(label="Link with Riot Sign On", emoji="🔐", url=url)
        )
        embed = discord.Embed(
            title="Connect your VALORANT profile",
            description=(
                "Authorize Aestron through Riot Sign On to unlock the interactive "
                "match lab, match history, and post-match coaching."
            ),
            color=0xFF4655,
        )
        embed.add_field(
            name="What is stored?",
            value="Your Riot ID, PUUID, routing shard, and Discord account link.",
            inline=False,
        )
        embed.add_field(
            name="Privacy",
            value=(
                "The login link expires in 10 minutes. OAuth tokens are not stored, "
                "and `/unlinkaccount` removes the link."
            ),
            inline=False,
        )
        embed.set_footer(text="Official Riot authorization • Opt in required")
        await ctx.send(
            embed=embed,
            view=view,
            ephemeral=True,
        )

    @commands.hybrid_command(
        name="valunlink",
        with_app_command=False,
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
        with_app_command=False,
        aliases=["valstats"],
        brief="Open an interactive VALORANT performance lab.",
        description=(
            "Analyze up to ten recent matches with match drill-downs, agent/map "
            "context, damage impact, and review prompts."
        ),
        usage="[member] [matches=8]",
    )
    @commands.cooldown(1, 20, commands.BucketType.user)
    async def vstats(
        self,
        ctx: commands.Context,
        member: discord.Member | discord.User | None = None,
        matches: commands.Range[int, 1, 10] = 8,
    ) -> None:
        """Open the complete interactive match-analysis dashboard."""
        target = member or ctx.author
        await ctx.defer(ephemeral=True)
        loaded = await self._load(ctx, target, limit=matches)
        if loaded is None:
            return
        account, summary, artwork = loaded
        view = ValorantStatsView(
            author_id=ctx.author.id,
            account=account,
            summary=summary,
            artwork=artwork,
        )
        await view.send(ctx)

    @commands.hybrid_command(
        with_app_command=False,
        aliases=["valhistory", "vmatches"],
        brief="Browse recent VALORANT matches interactively.",
        description=(
            "Show recent opted-in match results and select one for round-level stats."
        ),
        usage="[member] [matches=8]",
    )
    @commands.cooldown(1, 20, commands.BucketType.user)
    async def matchhistory(
        self,
        ctx: commands.Context,
        member: discord.Member | discord.User | None = None,
        matches: commands.Range[int, 1, 10] = 8,
    ) -> None:
        """Open the dashboard directly on recent match history."""
        target = member or ctx.author
        await ctx.defer(ephemeral=True)
        loaded = await self._load(ctx, target, limit=matches)
        if loaded is None:
            return
        account, summary, artwork = loaded
        view = ValorantStatsView(
            author_id=ctx.author.id,
            account=account,
            summary=summary,
            artwork=artwork,
            initial_page="matches",
        )
        await view.send(ctx)

    @commands.hybrid_command(
        with_app_command=False,
        name="valmatch",
        brief="Analyze one recent VALORANT match in depth.",
        description=(
            "Open a selected recent match with score, KDA, ACS, ADR, damage delta, "
            "opening duels, survival, multikills, objectives, and utility."
        ),
        usage="[number=1] [member]",
    )
    @commands.cooldown(1, 20, commands.BucketType.user)
    async def matchanalysis(
        self,
        ctx: commands.Context,
        number: commands.Range[int, 1, 10] = 1,
        member: discord.Member | discord.User | None = None,
    ) -> None:
        """Open one numbered match while retaining all dashboard controls."""
        target = member or ctx.author
        await ctx.defer(ephemeral=True)
        loaded = await self._load(ctx, target, limit=max(8, number))
        if loaded is None:
            return
        account, summary, artwork = loaded
        if number > len(summary.performances):
            await ctx.send(
                f"Only **{len(summary.performances)}** recent match(es) were available.",
                ephemeral=True,
            )
            return
        view = ValorantStatsView(
            author_id=ctx.author.id,
            account=account,
            summary=summary,
            artwork=artwork,
            initial_page=f"match:{number - 1}",
        )
        await view.send(ctx)

    @commands.hybrid_command(
        with_app_command=False,
        brief="Turn recent VALORANT matches into a review plan.",
        description=(
            "Build transparent practice prompts from opening duels, damage, survival, "
            "and utility across recent completed matches."
        ),
        usage="[member] [matches=8]",
    )
    @commands.cooldown(1, 20, commands.BucketType.user)
    async def valcoach(
        self,
        ctx: commands.Context,
        member: discord.Member | discord.User | None = None,
        matches: commands.Range[int, 1, 10] = 8,
    ) -> None:
        """Show transparent post-match coaching prompts."""
        target = member or ctx.author
        await ctx.defer(ephemeral=True)
        loaded = await self._load(ctx, target, limit=matches)
        if loaded is None:
            return
        account, summary, artwork = loaded
        view = ValorantStatsView(
            author_id=ctx.author.id,
            account=account,
            summary=summary,
            artwork=artwork,
            initial_page="coaching",
        )
        await view.send(ctx)

    async def _interaction_context(
        self, interaction: discord.Interaction
    ) -> commands.Context:
        """Build a supported hybrid context for shared command implementations."""
        return await commands.Context.from_interaction(interaction)

    @valorant.command(name="link", description="Securely link your Riot account.")
    @app_commands.checks.cooldown(1, 30, key=lambda interaction: interaction.user.id)
    async def slash_link(self, interaction: discord.Interaction) -> None:
        """Create a Riot Sign On link through `/valorant link`."""
        await self.linkaccount.callback(
            self, await self._interaction_context(interaction)
        )

    @valorant.command(name="unlink", description="Remove your linked Riot data.")
    @app_commands.checks.cooldown(1, 30, key=lambda interaction: interaction.user.id)
    async def slash_unlink(self, interaction: discord.Interaction) -> None:
        """Remove the Riot link through `/valorant unlink`."""
        await self.unlinkaccount.callback(
            self, await self._interaction_context(interaction)
        )

    @valorant.command(name="stats", description="Open your interactive match lab.")
    @app_commands.checks.cooldown(1, 20, key=lambda interaction: interaction.user.id)
    async def slash_stats(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        matches: app_commands.Range[int, 1, 10] = 8,
    ) -> None:
        """Open match statistics through `/valorant stats`."""
        await self.vstats.callback(
            self, await self._interaction_context(interaction), member, matches
        )

    @valorant.command(name="history", description="Browse recent matches.")
    @app_commands.checks.cooldown(1, 20, key=lambda interaction: interaction.user.id)
    async def slash_history(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        matches: app_commands.Range[int, 1, 10] = 8,
    ) -> None:
        """Browse history through `/valorant history`."""
        await self.matchhistory.callback(
            self, await self._interaction_context(interaction), member, matches
        )

    @valorant.command(name="match", description="Analyze one recent match in depth.")
    @app_commands.checks.cooldown(1, 20, key=lambda interaction: interaction.user.id)
    async def slash_match(
        self,
        interaction: discord.Interaction,
        number: app_commands.Range[int, 1, 10] = 1,
        member: discord.Member | None = None,
    ) -> None:
        """Analyze a match through `/valorant match`."""
        await self.matchanalysis.callback(
            self, await self._interaction_context(interaction), number, member
        )

    @valorant.command(name="coach", description="Build a match-based practice plan.")
    @app_commands.checks.cooldown(1, 20, key=lambda interaction: interaction.user.id)
    async def slash_coach(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        matches: app_commands.Range[int, 1, 10] = 8,
    ) -> None:
        """Build coaching prompts through `/valorant coach`."""
        await self.valcoach.callback(
            self, await self._interaction_context(interaction), member, matches
        )
