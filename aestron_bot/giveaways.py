"""Restart-safe giveaways and native Discord polls."""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .moderation import parse_duration

LOGGER = logging.getLogger(__name__)


class GiveawayView(discord.ui.View):
    """Persistent entry controls for every active giveaway."""

    def __init__(self, *, ended: bool = False) -> None:
        """Create restart-safe entry and leave buttons."""
        super().__init__(timeout=None)
        for item in self.children:
            item.disabled = ended

    async def _cog(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Giveaways")
        if cog is None:
            await interaction.response.send_message(
                "Giveaway service is unavailable.", ephemeral=True
            )
        return cog

    @discord.ui.button(
        label="Enter",
        emoji="🎉",
        style=discord.ButtonStyle.success,
        custom_id="aestron:giveaway:enter:v1",
    )
    async def enter(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Enter the giveaway represented by this message."""
        if cog := await self._cog(interaction):
            await cog.update_entry(interaction, enter=True)

    @discord.ui.button(
        label="Leave",
        emoji="↩️",
        style=discord.ButtonStyle.secondary,
        custom_id="aestron:giveaway:leave:v1",
    )
    async def leave(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Leave the giveaway represented by this message."""
        if cog := await self._cog(interaction):
            await cog.update_entry(interaction, enter=False)


class Giveaways(commands.Cog):
    """Run persistent giveaways and Discord-native polls."""

    giveaway = app_commands.Group(
        name="giveaway", description="Create and manage restart-safe giveaways."
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot used by the due-giveaway worker."""
        self.bot = bot

    async def cog_load(self) -> None:
        """Register persistent controls, storage, and the due-date worker."""
        self.bot.add_view(GiveawayView())
        if not self.bot.database.connected:
            return
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS aestron_giveaways (
                    message_id BIGINT PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    channel_id BIGINT NOT NULL,
                    host_id BIGINT NOT NULL,
                    prize TEXT NOT NULL,
                    winner_count SMALLINT NOT NULL,
                    ends_at TIMESTAMPTZ NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    ended_at TIMESTAMPTZ,
                    CHECK (winner_count BETWEEN 1 AND 20),
                    CHECK (status IN ('active', 'ending', 'ended'))
                )
                """
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS aestron_giveaway_entries (
                    message_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    entered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (message_id, user_id)
                )
                """
            )
            await connection.execute(
                "CREATE INDEX IF NOT EXISTS aestron_giveaways_due_idx "
                "ON aestron_giveaways (status, ends_at)"
            )
            await connection.execute(
                "UPDATE aestron_giveaways SET status = 'active' WHERE status = 'ending'"
            )
        self.finish_due_giveaways.start()

    async def cog_unload(self) -> None:
        """Stop the due-date worker during a clean shutdown."""
        self.finish_due_giveaways.cancel()

    @staticmethod
    def _embed(row, *, entries: int, winners: list[int] | None = None) -> discord.Embed:
        ended = row["status"] == "ended" or winners is not None
        embed = discord.Embed(
            title="🎉 Giveaway ended" if ended else "🎉 Giveaway",
            description=str(row["prize"])[:4096],
            color=discord.Color.orange() if ended else discord.Color.green(),
            timestamp=row["ends_at"],
        )
        embed.add_field(name="Hosted by", value=f"<@{row['host_id']}>")
        embed.add_field(name="Winners", value=str(row["winner_count"]))
        embed.add_field(name="Entries", value=str(entries))
        if ended:
            embed.add_field(
                name="Selected winners",
                value=(
                    " ".join(f"<@{user_id}>" for user_id in winners)
                    if winners
                    else (
                        "See the channel announcement"
                        if winners is None
                        else "Not enough eligible entries"
                    )
                ),
                inline=False,
            )
            embed.set_footer(text=f"Giveaway ID: {row['message_id']} · Ended")
        else:
            embed.add_field(
                name="Ends",
                value=discord.utils.format_dt(row["ends_at"], "R"),
                inline=False,
            )
            embed.set_footer(
                text=f"Giveaway ID: {row['message_id']} · Use the buttons below"
            )
        return embed

    async def _create(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        host: discord.abc.User,
        duration: str,
        winner_count: int,
        prize: str,
    ) -> discord.Message:
        if channel.guild.id != guild.id:
            raise commands.BadArgument("Choose a text channel in this server.")
        permissions = channel.permissions_for(guild.me)
        missing = [
            name
            for name in ("view_channel", "send_messages", "embed_links")
            if not getattr(permissions, name, False)
        ]
        if missing:
            raise commands.BotMissingPermissions(missing)
        delta = parse_duration(duration)
        if delta < timedelta(seconds=10):
            raise commands.BadArgument("Giveaways must run for at least 10 seconds.")
        prize = prize.strip()
        if not prize or len(prize) > 1000:
            raise commands.BadArgument("The prize must contain 1-1000 characters.")
        ends_at = discord.utils.utcnow() + delta
        provisional = {
            "message_id": 0,
            "host_id": host.id,
            "prize": prize,
            "winner_count": winner_count,
            "ends_at": ends_at,
            "status": "active",
        }
        message = await channel.send(
            embed=self._embed(provisional, entries=0), view=GiveawayView()
        )
        async with self.bot.database.pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO aestron_giveaways "
                "(message_id, guild_id, channel_id, host_id, prize, winner_count, ends_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                message.id,
                guild.id,
                channel.id,
                host.id,
                prize,
                winner_count,
                ends_at,
            )
        provisional["message_id"] = message.id
        await message.edit(embed=self._embed(provisional, entries=0))
        return message

    async def update_entry(
        self, interaction: discord.Interaction, *, enter: bool
    ) -> None:
        """Add or remove one member from an active giveaway atomically."""
        if interaction.message is None or interaction.guild is None:
            await interaction.response.send_message(
                "This giveaway is unavailable.", ephemeral=True
            )
            return
        async with self.bot.database.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT status, ends_at FROM aestron_giveaways WHERE message_id = $1",
                interaction.message.id,
            )
            if row is None or row["status"] != "active":
                await interaction.response.send_message(
                    "This giveaway has ended.", ephemeral=True
                )
                return
            if row["ends_at"] <= discord.utils.utcnow():
                await interaction.response.send_message(
                    "This giveaway is ending now.", ephemeral=True
                )
                return
            if enter:
                await connection.execute(
                    "INSERT INTO aestron_giveaway_entries (message_id, user_id) "
                    "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    interaction.message.id,
                    interaction.user.id,
                )
            else:
                await connection.execute(
                    "DELETE FROM aestron_giveaway_entries "
                    "WHERE message_id = $1 AND user_id = $2",
                    interaction.message.id,
                    interaction.user.id,
                )
        await interaction.response.send_message(
            "You entered the giveaway." if enter else "You left the giveaway.",
            ephemeral=True,
        )

    async def _eligible_ids(self, row) -> list[int]:
        guild = self.bot.get_guild(int(row["guild_id"]))
        async with self.bot.database.pool.acquire() as connection:
            ids = await connection.fetch(
                "SELECT user_id FROM aestron_giveaway_entries WHERE message_id = $1",
                row["message_id"],
            )
        if guild is None:
            return []
        return [
            int(item["user_id"])
            for item in ids
            if (member := guild.get_member(int(item["user_id"]))) is not None
            and not member.bot
        ]

    async def _finish(self, message_id: int) -> list[int]:
        async with self.bot.database.pool.acquire() as connection:
            row = await connection.fetchrow(
                "UPDATE aestron_giveaways SET status = 'ending' "
                "WHERE message_id = $1 AND status = 'active' RETURNING *",
                message_id,
            )
        if row is None:
            return []
        eligible = await self._eligible_ids(row)
        count = min(int(row["winner_count"]), len(eligible))
        winners = secrets.SystemRandom().sample(eligible, count) if count else []
        async with self.bot.database.pool.acquire() as connection:
            finished = await connection.fetchrow(
                "UPDATE aestron_giveaways SET status = 'ended', ended_at = NOW() "
                "WHERE message_id = $1 RETURNING *",
                message_id,
            )
        guild = self.bot.get_guild(int(row["guild_id"]))
        channel = guild.get_channel(int(row["channel_id"])) if guild else None
        if isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(
                    embed=self._embed(finished, entries=len(eligible), winners=winners),
                    view=GiveawayView(ended=True),
                )
                if winners:
                    await channel.send(
                        f"Congratulations {' '.join(f'<@{item}>' for item in winners)}! "
                        f"You won **{row['prize']}**. {message.jump_url}",
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                else:
                    await channel.send(
                        f"Giveaway `{message_id}` ended without enough eligible entries."
                    )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                LOGGER.exception("Could not finalize giveaway message=%s", message_id)
        return winners

    @tasks.loop(seconds=15)
    async def finish_due_giveaways(self) -> None:
        """Resume and finish due giveaways after any bot restart."""
        async with self.bot.database.pool.acquire() as connection:
            due = await connection.fetch(
                "SELECT message_id FROM aestron_giveaways "
                "WHERE status = 'active' AND ends_at <= NOW() ORDER BY ends_at LIMIT 25"
            )
        for row in due:
            await self._finish(int(row["message_id"]))

    @finish_due_giveaways.before_loop
    async def before_finish_worker(self) -> None:
        """Wait for Discord cache readiness before resolving guild members."""
        await self.bot.wait_until_ready()

    async def _reroll(self, message_id: int, winner_count: int = 1) -> list[int]:
        async with self.bot.database.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM aestron_giveaways "
                "WHERE message_id = $1 AND status = 'ended'",
                message_id,
            )
        if row is None:
            raise commands.BadArgument("That is not an ended Aestron giveaway.")
        eligible = await self._eligible_ids(row)
        count = min(winner_count, len(eligible))
        if not count:
            raise commands.BadArgument("There are no eligible entries to reroll.")
        return secrets.SystemRandom().sample(eligible, count)

    @commands.cooldown(1, 10, commands.BucketType.guild)
    @commands.hybrid_command(
        with_app_command=False,
        brief="Start a restart-safe giveaway.",
        description="Create a persistent button giveaway with a duration and winner count.",
        usage="<duration> <winner_count> [channel] <prize>",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def giveawaystart(
        self,
        ctx: commands.Context,
        duration: str,
        winner_count: commands.Range[int, 1, 20],
        channel: discord.TextChannel | None = None,
        *,
        prize: str,
    ) -> None:
        """Create a giveaway through a prefix command."""
        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel):
            raise commands.BadArgument("Choose a text channel.")
        message = await self._create(
            ctx.guild, target, ctx.author, duration, winner_count, prize
        )
        await ctx.send(f"Giveaway created: {message.jump_url}", ephemeral=True)

    @commands.cooldown(1, 15, commands.BucketType.guild)
    @commands.hybrid_command(
        with_app_command=False,
        brief="Reroll an ended Aestron giveaway.",
        description="Select one new eligible winner from a persisted giveaway.",
        usage="<giveaway_message_id>",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def reroll(self, ctx: commands.Context, giveaway_message_id: int) -> None:
        """Reroll a giveaway through a prefix command."""
        winners = await self._reroll(giveaway_message_id)
        await ctx.send(
            f"Rerolled winner: {' '.join(f'<@{item}>' for item in winners)}",
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    @commands.cooldown(1, 10, commands.BucketType.member)
    @commands.hybrid_command(
        with_app_command=False,
        aliases=["makepoll"],
        brief="Create a Discord-native poll.",
        description="Create a yes/no poll managed by Discord, so restarts do not affect it.",
        usage="<duration> <question>",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def poll(
        self, ctx: commands.Context, duration: str, *, question: str
    ) -> None:
        """Create a native yes/no poll through a prefix command."""
        delta = parse_duration(duration)
        if delta < timedelta(hours=1):
            raise commands.BadArgument(
                "Discord-native polls must run for at least 1 hour."
            )
        poll = discord.Poll(question=question[:300], duration=delta)
        poll.add_answer(text="Yes", emoji="✅").add_answer(text="No", emoji="❌")
        await ctx.send(poll=poll)

    @commands.cooldown(2, 10, commands.BucketType.member)
    @commands.hybrid_command(
        with_app_command=False,
        brief="Choose one winner from mentioned members.",
        description="Randomly select one unique mentioned member without off-by-one bias.",
        usage="<members...>",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def instantgiveaway(
        self, ctx: commands.Context, members: commands.Greedy[discord.Member]
    ) -> None:
        """Select an instant winner through a prefix command."""
        unique = list({member.id: member for member in members}.values())
        if not unique:
            raise commands.BadArgument("Mention at least one member.")
        winner = secrets.choice(unique)
        await ctx.send(f"{winner.mention} won the instant giveaway!")

    @giveaway.command(name="start", description="Start a restart-safe giveaway.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 20, key=lambda interaction: interaction.guild_id)
    async def slash_start(
        self,
        interaction: discord.Interaction,
        duration: str,
        winner_count: app_commands.Range[int, 1, 20],
        prize: str,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Start a giveaway through slash commands."""
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                "Choose a text channel.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        message = await self._create(
            interaction.guild,
            target,
            interaction.user,
            duration,
            winner_count,
            prize,
        )
        await interaction.followup.send(
            f"Giveaway created: {message.jump_url}", ephemeral=True
        )

    @giveaway.command(name="end", description="End an active giveaway now.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.guild_id)
    async def slash_end(
        self, interaction: discord.Interaction, message_id: str
    ) -> None:
        """End a giveaway through slash commands."""
        if not message_id.isdecimal():
            await interaction.response.send_message(
                "Message ID must contain only numbers.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        winners = await self._finish(int(message_id))
        await interaction.followup.send(
            "Giveaway ended. Winners: "
            + (" ".join(f"<@{item}>" for item in winners) or "none"),
            ephemeral=True,
        )

    @giveaway.command(name="reroll", description="Reroll an ended giveaway.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.guild_id)
    async def slash_reroll(
        self,
        interaction: discord.Interaction,
        message_id: str,
        winner_count: app_commands.Range[int, 1, 20] = 1,
    ) -> None:
        """Reroll a giveaway through slash commands."""
        if not message_id.isdecimal():
            await interaction.response.send_message(
                "Message ID must contain only numbers.", ephemeral=True
            )
            return
        winners = await self._reroll(int(message_id), winner_count)
        await interaction.response.send_message(
            "Rerolled: " + " ".join(f"<@{item}>" for item in winners)
        )

    @giveaway.command(name="status", description="Show a persisted giveaway's status.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.cooldown(2, 10, key=lambda interaction: interaction.guild_id)
    async def slash_status(
        self, interaction: discord.Interaction, message_id: str
    ) -> None:
        """Show giveaway state through slash commands."""
        if not message_id.isdecimal():
            await interaction.response.send_message(
                "Message ID must contain only numbers.", ephemeral=True
            )
            return
        async with self.bot.database.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT *, (SELECT COUNT(*) FROM aestron_giveaway_entries e "
                "WHERE e.message_id = g.message_id) AS entries "
                "FROM aestron_giveaways g WHERE message_id = $1",
                int(message_id),
            )
        if row is None:
            await interaction.response.send_message(
                "That giveaway was not found.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=self._embed(row, entries=int(row["entries"])), ephemeral=True
        )
