"""Owner-confirmed cleanup of guilds with established inactivity."""

from __future__ import annotations

import asyncio
import contextlib
import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO, StringIO

import discord
from discord.ext import commands

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PruneCandidate:
    """One guild whose complete observation window is inactive."""

    guild_id: int
    name: str
    member_count: int
    first_seen_at: datetime
    last_active_at: datetime | None


@dataclass(frozen=True, slots=True)
class PruneResult:
    """One attempted guild departure and its audit outcome."""

    guild_id: int
    name: str
    outcome: str
    detail: str


class GuildPruneService:
    """Preview and execute conservative inactive-guild departures."""

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot and its aggregate activity database."""
        self.bot = bot

    async def candidates(
        self,
        *,
        inactive_for: timedelta,
        protected_guild_id: int,
    ) -> list[PruneCandidate]:
        """Return only guilds observed for the entire inactivity window."""
        cutoff = discord.utils.utcnow() - inactive_for
        async with self.bot.database.pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT guild_id, first_seen_at, last_active_at "
                "FROM aestron_guild_activity "
                "WHERE first_seen_at <= $1::TIMESTAMPTZ "
                "AND (last_active_at IS NULL OR last_active_at <= $1::TIMESTAMPTZ)",
                cutoff,
            )
        activity = {int(row["guild_id"]): row for row in rows}
        candidates = []
        for guild in self.bot.guilds:
            if guild.id == protected_guild_id or guild.id not in activity:
                continue
            row = activity[guild.id]
            candidates.append(
                PruneCandidate(
                    guild_id=guild.id,
                    name=guild.name,
                    member_count=guild.member_count or 0,
                    first_seen_at=row["first_seen_at"],
                    last_active_at=row["last_active_at"],
                )
            )
        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.last_active_at or candidate.first_seen_at,
                candidate.guild_id,
            ),
        )

    @staticmethod
    def preview_embed(
        candidates: list[PruneCandidate], inactive_days: int
    ) -> discord.Embed:
        """Build a bounded confirmation preview."""
        lines = []
        for candidate in candidates[:15]:
            last_active = (
                discord.utils.format_dt(candidate.last_active_at, "R")
                if candidate.last_active_at
                else "No activity during observation"
            )
            lines.append(
                f"**{candidate.name[:45]}** (`{candidate.guild_id}`) · "
                f"{candidate.member_count:,} members · {last_active}"
            )
        if len(candidates) > 15:
            lines.append(f"…and {len(candidates) - 15:,} more in the result CSV.")
        embed = discord.Embed(
            title="Inactive guild cleanup preview",
            description=(
                f"**{len(candidates):,}** guild(s) have been observed for at least "
                f"**{inactive_days} days** without human messages or commands.\n\n"
                + ("\n".join(lines) or "No guild is currently eligible.")
            ),
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Safety rules",
            value=(
                "The current guild is protected. Untracked guilds are excluded. "
                "Activity is checked again before leaving."
            ),
            inline=False,
        )
        return embed

    @staticmethod
    def _notification_channel(guild: discord.Guild) -> discord.TextChannel | None:
        """Choose the guild's preferred writable public channel for a farewell."""
        preferred = (
            guild.system_channel,
            guild.public_updates_channel,
            guild.rules_channel,
            *guild.text_channels,
        )
        seen: set[int] = set()
        for channel in preferred:
            if channel is None or channel.id in seen:
                continue
            seen.add(channel.id)
            permissions = channel.permissions_for(guild.me)
            if permissions.view_channel and permissions.send_messages:
                return channel
        return None

    async def _send_notice(
        self,
        guild: discord.Guild,
        farewell_message: str | None,
        invite_url: str | None,
    ) -> str:
        """Send the optional departure notice and return its delivery status."""
        if farewell_message is None and invite_url is None:
            return "not_requested"
        channel = self._notification_channel(guild)
        if channel is None:
            return "no_writable_channel"
        content = farewell_message or "Aestron is leaving this server."
        if invite_url:
            content = f"{content}\n\n{invite_url}"
        try:
            await channel.send(
                content[:2000],
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            LOGGER.warning("Could not send prune notice guild=%s", guild.id)
            return "delivery_failed"
        return f"sent_in:{channel.id}"

    async def execute(
        self,
        candidates: list[PruneCandidate],
        *,
        inactive_for: timedelta,
        protected_guild_id: int,
        farewell_message: str | None,
        invite_url: str | None,
    ) -> list[PruneResult]:
        """Revalidate a snapshot, optionally notify, and leave eligible guilds."""
        if not candidates:
            return []
        cutoff = discord.utils.utcnow() - inactive_for
        candidate_ids = [candidate.guild_id for candidate in candidates]
        async with self.bot.database.pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT guild_id, first_seen_at, last_active_at "
                "FROM aestron_guild_activity "
                "WHERE guild_id = ANY($1::BIGINT[])",
                candidate_ids,
            )
        activity = {int(row["guild_id"]): row for row in rows}
        results = []
        for candidate in candidates:
            guild = self.bot.get_guild(candidate.guild_id)
            row = activity.get(candidate.guild_id)
            if guild is None:
                results.append(
                    PruneResult(candidate.guild_id, candidate.name, "skipped", "gone")
                )
                continue
            if guild.id == protected_guild_id:
                results.append(
                    PruneResult(
                        guild.id, guild.name, "skipped", "protected_control_guild"
                    )
                )
                continue
            if (
                row is None
                or row["first_seen_at"] > cutoff
                or (
                    row["last_active_at"] is not None
                    and row["last_active_at"] > cutoff
                )
            ):
                results.append(
                    PruneResult(
                        guild.id, guild.name, "skipped", "activity_changed"
                    )
                )
                continue
            notice = await self._send_notice(guild, farewell_message, invite_url)
            try:
                await guild.leave()
            except (discord.Forbidden, discord.HTTPException) as error:
                LOGGER.warning("Could not leave inactive guild=%s", guild.id)
                results.append(
                    PruneResult(guild.id, guild.name, "failed", type(error).__name__)
                )
                continue
            results.append(PruneResult(guild.id, guild.name, "left", notice))
            await asyncio.sleep(0.25)
        return results

    @staticmethod
    def results_file(results: list[PruneResult]) -> discord.File:
        """Return a spreadsheet-safe audit of the confirmed cleanup run."""
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("guild_id", "guild_name", "outcome", "detail"))
        for result in results:
            name = (
                "'" + result.name
                if result.name.startswith(("=", "+", "-", "@"))
                else result.name
            )
            writer.writerow((result.guild_id, name, result.outcome, result.detail))
        return discord.File(
            BytesIO(output.getvalue().encode("utf-8-sig")),
            filename="aestron-guild-prune-results.csv",
        )


class GuildPruneConfirmation(discord.ui.View):
    """Invoker-bound confirmation for one immutable candidate snapshot."""

    def __init__(
        self,
        service: GuildPruneService,
        *,
        owner_id: int,
        protected_guild_id: int,
        candidates: list[PruneCandidate],
        inactive_days: int,
        farewell_message: str | None,
        invite_url: str | None,
    ) -> None:
        """Store the exact preview inputs for revalidation on confirmation."""
        super().__init__(timeout=120)
        self.service = service
        self.owner_id = owner_id
        self.protected_guild_id = protected_guild_id
        self.candidates = candidates
        self.inactive_days = inactive_days
        self.farewell_message = farewell_message
        self.invite_url = invite_url
        self.message: discord.Message | None = None

    async def on_timeout(self) -> None:
        """Disable an expired destructive confirmation without taking action."""
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Allow only the owner who generated this preview."""
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "Only the bot owner who opened this preview can confirm it.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Confirm guild cleanup", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Acknowledge immediately, revalidate, and execute the cleanup."""
        del button
        running = discord.Embed(
            title="Guild cleanup running",
            description=f"Revalidating {len(self.candidates):,} candidate guild(s)…",
            color=discord.Color.orange(),
        )
        await interaction.response.edit_message(embed=running, view=None)
        results = await self.service.execute(
            self.candidates,
            inactive_for=timedelta(days=self.inactive_days),
            protected_guild_id=self.protected_guild_id,
            farewell_message=self.farewell_message,
            invite_url=self.invite_url,
        )
        left = sum(result.outcome == "left" for result in results)
        skipped = sum(result.outcome == "skipped" for result in results)
        failed = sum(result.outcome == "failed" for result in results)
        complete = discord.Embed(
            title="Guild cleanup complete",
            description=(
                f"Left **{left:,}** · Skipped **{skipped:,}** · "
                f"Failed **{failed:,}**"
            ),
            color=discord.Color.green() if not failed else discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        if interaction.message is not None:
            await interaction.message.edit(embed=complete, view=None)
        await interaction.followup.send(
            file=self.service.results_file(results), ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Cancel without mutating any guild."""
        del button
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Guild cleanup cancelled",
                description="No guilds were contacted or left.",
                color=discord.Color.green(),
            ),
            view=None,
        )
        self.stop()
