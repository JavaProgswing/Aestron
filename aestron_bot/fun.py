"""Fast, image-first games and social commands with interactive controls."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import itertools
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from .fun_ui import render_fun_dashboard

ACCENT = 0xFF4655


def _image_embed() -> discord.Embed:
    """Return the minimal Discord frame used by rendered fun dashboards."""
    return discord.Embed(color=ACCENT).set_image(url="attachment://fun-dashboard.png")


async def _dashboard_file(embed: discord.Embed) -> discord.File:
    """Render a fun dashboard off the event loop."""
    image = await asyncio.to_thread(render_fun_dashboard, embed)
    return discord.File(BytesIO(image), filename="fun-dashboard.png")


async def _edit_dashboard(
    interaction: discord.Interaction,
    embed: discord.Embed,
    view: discord.ui.View,
) -> None:
    """Acknowledge a component before rendering and replacing its dashboard."""
    await interaction.response.defer()
    file = await _dashboard_file(embed)
    if interaction.message is not None:
        await interaction.message.edit(
            embed=_image_embed(), view=view, attachments=[file]
        )


async def _send_dashboard(
    ctx: commands.Context,
    embed: discord.Embed,
    *,
    view: discord.ui.View | None = None,
    ephemeral: bool = False,
) -> discord.Message:
    """Render and send one image-first command response."""
    file = await _dashboard_file(embed)
    return await ctx.send(
        embed=_image_embed(), file=file, view=view, ephemeral=ephemeral
    )


async def _respond_dashboard(
    interaction: discord.Interaction,
    embed: discord.Embed,
    *,
    view: discord.ui.View | None = None,
) -> discord.Message:
    """Defer a slash command and send its rendered dashboard."""
    await interaction.response.defer(thinking=True)
    file = await _dashboard_file(embed)
    await interaction.followup.send(embed=_image_embed(), file=file, view=view)
    return await interaction.original_response()


def _pick(values: tuple[str, ...] | list[str]) -> str:
    """Choose one value using the operating system random source."""
    return values[secrets.randbelow(len(values))]


def _coinflip_embed(count: int) -> discord.Embed:
    """Build a bounded result for one or more fair coin flips."""
    results = [_pick(("Heads", "Tails")) for _ in range(count)]
    heads = results.count("Heads")
    embed = discord.Embed(
        title="Coin flip",
        description=" ".join("H" if result == "Heads" else "T" for result in results),
        color=ACCENT,
    )
    streaks = [(value, len(list(group))) for value, group in itertools.groupby(results)]
    streak_name, streak = max(streaks, key=lambda item: item[1])
    embed.add_field(name="Heads", value=f"**{heads}** · {heads / count:.0%}")
    embed.add_field(
        name="Tails", value=f"**{count - heads}** · {(count - heads) / count:.0%}"
    )
    embed.add_field(name="Longest run", value=f"**{streak}** {streak_name.lower()}")
    embed.set_footer(text="H = heads · T = tails · secure virtual randomness")
    return embed


def _dice_embed(dice: int, sides: int) -> discord.Embed:
    """Build a dice result with individual rolls, total, and average."""
    values = [secrets.randbelow(sides) + 1 for _ in range(dice)]
    embed = discord.Embed(
        title=f"Roll · {dice}d{sides}",
        description=" + ".join(map(str, values)) + f" = **{sum(values)}**",
        color=ACCENT,
    )
    if dice > 1:
        embed.add_field(name="Highest", value=str(max(values)))
        embed.add_field(name="Lowest", value=str(min(values)))
        embed.add_field(name="Average", value=f"{sum(values) / dice:.1f}")
        frequencies = sorted(
            ((value, values.count(value)) for value in set(values)),
            key=lambda item: (-item[1], item[0]),
        )
        embed.add_field(
            name="Most frequent",
            value=", ".join(
                f"{value} × {frequency}" for value, frequency in frequencies[:3]
            ),
            inline=False,
        )
    embed.set_footer(text=f"Possible range: {dice}–{dice * sides}")
    return embed


def _options(value: str) -> list[str]:
    """Validate a comma- or pipe-separated choice list."""
    separator = "|" if "|" in value else ","
    choices = [item.strip() for item in value.split(separator) if item.strip()]
    if not 2 <= len(choices) <= 25:
        raise commands.BadArgument("Provide between 2 and 25 non-empty options.")
    if any(len(item) > 100 for item in choices):
        raise commands.BadArgument("Each option must be at most 100 characters.")
    return choices


def _rating(user_id: int, subject: str) -> tuple[str, int]:
    """Return a normalized subject and stable user-specific rating."""
    normalized = " ".join(subject.split())
    if not 1 <= len(normalized) <= 100:
        raise commands.BadArgument("The subject must be 1 to 100 characters long.")
    seed = f"{user_id}:{normalized.casefold()}".encode()
    score = int.from_bytes(hashlib.blake2b(seed, digest_size=2).digest()) % 101
    return normalized, score


EIGHT_BALL_ANSWERS = (
    "It is certain.",
    "Outlook good.",
    "Signs point to yes.",
    "Ask again later.",
    "Cannot predict now.",
    "Don't count on it.",
    "Very doubtful.",
    "My sources say no.",
)

WOULD_YOU_RATHER = (
    ("Always know when someone is lying", "Get away with one lie a day"),
    ("Explore a new planet", "Explore the deepest point of the ocean"),
    ("Have perfect aim", "Have perfect game sense"),
    ("Pause time for ten seconds", "Rewind time for ten seconds"),
    ("Give up music for a year", "Give up games for a year"),
    ("Be the funniest person in every room", "Be the smartest"),
    ("Only play ranked", "Never play ranked again"),
    ("Have unlimited travel", "Have unlimited food"),
)


class InvokerView(discord.ui.View):
    """Base view which only accepts input from the command invoker."""

    def __init__(self, author_id: int, *, timeout: float = 90) -> None:
        """Store the user allowed to operate the view."""
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Reject component input from anyone except the invoker."""
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Run the command yourself to start a game.", ephemeral=True
        )
        return False

    async def on_timeout(self) -> None:
        """Disable expired game controls."""
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        """Return a private failure after a component has been acknowledged."""
        message = "That game action failed safely. Try the command again."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class ReplayView(InvokerView):
    """Rerun a bounded local game without producing channel spam."""

    def __init__(
        self, author_id: int, renderer: Callable[[], discord.Embed], label: str
    ) -> None:
        """Store the replay renderer and apply its action label."""
        super().__init__(author_id, timeout=120)
        self.renderer = renderer
        self.replays = 0
        self.replay.label = label

    @discord.ui.button(label="Again", style=discord.ButtonStyle.primary)
    async def replay(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Render the next bounded replay in place."""
        self.replays += 1
        if self.replays >= 5:
            button.disabled = True
        embed = self.renderer()
        embed.set_footer(
            text=f"Replay {self.replays}/5 • Run the command for a fresh session"
        )
        await _edit_dashboard(interaction, embed, self)


class DecisionView(InvokerView):
    """Re-pick or progressively eliminate submitted choices."""

    def __init__(self, author_id: int, choices: list[str]) -> None:
        """Copy validated choices into an invoker-owned session."""
        super().__init__(author_id, timeout=120)
        self.choices = choices.copy()
        self.picks = 0
        self.eliminated: list[str] = []

    def embed(self) -> discord.Embed:
        """Pick an option and show the remaining decision pool."""
        chosen = _pick(self.choices)
        self.picks += 1
        embed = discord.Embed(
            title="Decision room",
            description=f"I choose **{discord.utils.escape_markdown(chosen)}**.",
            color=ACCENT,
        ).add_field(
            name=f"Remaining options ({len(self.choices)})",
            value=" • ".join(
                discord.utils.escape_markdown(value) for value in self.choices
            )[:1024],
            inline=False,
        )
        if self.eliminated:
            embed.add_field(
                name="Eliminated",
                value=" · ".join(
                    discord.utils.escape_markdown(value)
                    for value in self.eliminated[-5:]
                )[:1024],
                inline=False,
            )
        embed.set_footer(text=f"Pick {self.picks} · secure virtual randomness")
        return embed

    @discord.ui.button(label="Choose again", style=discord.ButtonStyle.primary)
    async def again(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Pick again from the current pool."""
        await _edit_dashboard(interaction, self.embed(), self)

    @discord.ui.button(label="Eliminate one", style=discord.ButtonStyle.danger)
    async def eliminate(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Remove a random option before making another pick."""
        if len(self.choices) <= 2:
            button.disabled = True
            await interaction.response.send_message(
                "Two options remain; make the final choice.", ephemeral=True
            )
            return
        removed = self.choices.pop(secrets.randbelow(len(self.choices)))
        self.eliminated.append(removed)
        embed = self.embed()
        embed.description = f"Eliminated ~~{discord.utils.escape_markdown(removed)}~~\n\n{embed.description}"
        await _edit_dashboard(interaction, embed, self)


class RockPaperScissorsView(InvokerView):
    """Best-of-five rock-paper-scissors match."""

    choices = ("rock", "paper", "scissors")
    wins_against = {"rock": "scissors", "paper": "rock", "scissors": "paper"}

    def __init__(self, author_id: int) -> None:
        """Start a scoreless first-to-three match."""
        super().__init__(author_id, timeout=120)
        self.player_score = 0
        self.bot_score = 0
        self.round = 0
        self.history: list[str] = []

    async def _play(self, interaction: discord.Interaction, choice: str) -> None:
        bot_choice = _pick(self.choices)
        if choice == bot_choice:
            outcome = "Round drawn"
            color = discord.Color.gold()
        elif self.wins_against[choice] == bot_choice:
            self.player_score += 1
            outcome = "You take the round!"
            color = discord.Color.green()
        else:
            self.bot_score += 1
            outcome = "Aestron takes the round!"
            color = discord.Color.red()
        self.round += 1
        match_finished = (
            self.player_score == 3 or self.bot_score == 3 or self.round >= 7
        )
        if match_finished:
            if self.player_score > self.bot_score:
                outcome = "You won the match"
                color = discord.Color.green()
            elif self.bot_score > self.player_score:
                outcome = "Aestron won the match"
                color = discord.Color.red()
            else:
                outcome = "The match ended level"
                color = discord.Color.gold()
        embed = discord.Embed(
            title=outcome,
            description=(
                f"You chose **{choice.title()}**\n"
                f"Aestron chose **{bot_choice.title()}**\n\n"
                f"**You {self.player_score} — {self.bot_score} Aestron**"
            ),
            color=color,
        )
        self.history.append(f"R{self.round}: {choice.title()} vs {bot_choice.title()}")
        embed.add_field(
            name="Round log", value="\n".join(self.history[-5:]), inline=False
        )
        embed.set_footer(text=f"Round {self.round} • First to 3 wins")
        if match_finished:
            for item in self.children:
                item.disabled = True
        await _edit_dashboard(interaction, embed, self)
        if match_finished:
            self.stop()

    @discord.ui.button(label="Rock")
    async def rock(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Play rock."""
        await self._play(interaction, "rock")

    @discord.ui.button(label="Paper")
    async def paper(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Play paper."""
        await self._play(interaction, "paper")

    @discord.ui.button(label="Scissors")
    async def scissors(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Play scissors."""
        await self._play(interaction, "scissors")


@dataclass(frozen=True, slots=True)
class TriviaQuestion:
    """A reviewed multiple-choice trivia question."""

    prompt: str
    choices: tuple[str, str, str, str]
    answer: int
    explanation: str


TRIVIA_QUESTIONS = (
    TriviaQuestion(
        "Which planet has the shortest day?",
        ("Earth", "Jupiter", "Mars", "Mercury"),
        1,
        "Jupiter rotates once in roughly ten hours.",
    ),
    TriviaQuestion(
        "What does HTTP status 404 mean?",
        ("Unauthorized", "Not found", "Server error", "Created"),
        1,
        "404 indicates that the requested resource was not found.",
    ),
    TriviaQuestion(
        "Which VALORANT role commonly creates safe entry space?",
        ("Duelist", "Sentinel", "Controller", "Initiator"),
        0,
        "Duelists are designed to take fights and create entry space.",
    ),
    TriviaQuestion(
        "What is the largest ocean on Earth?",
        ("Atlantic", "Indian", "Arctic", "Pacific"),
        3,
        "The Pacific Ocean is the largest and deepest ocean basin.",
    ),
    TriviaQuestion(
        "In Python, which keyword defines an asynchronous function?",
        ("await", "async", "defer", "yield"),
        1,
        "An asynchronous function starts with `async def`.",
    ),
)


class TriviaAnswerButton(discord.ui.Button):
    """One answer on an interactive trivia card."""

    def __init__(self, index: int, label: str) -> None:
        """Create a numbered answer button."""
        super().__init__(label=f"{index + 1}. {label}", row=index // 2)
        self.answer_index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        """Reveal whether this answer is correct."""
        view = self.view
        if not isinstance(view, TriviaView):
            return
        correct = self.answer_index == view.question.answer
        if correct:
            view.score += 1
        for item in view.children:
            item.disabled = True
            if isinstance(item, TriviaAnswerButton):
                item.style = (
                    discord.ButtonStyle.success
                    if item.answer_index == view.question.answer
                    else discord.ButtonStyle.secondary
                )
        answer = view.question.choices[view.question.answer]
        embed = discord.Embed(
            title="Correct" if correct else "Not quite",
            description=(
                f"**Answer:** {answer}\n\n{view.question.explanation}\n\n"
                f"**Score:** {view.score}/{view.round_number}"
            ),
            color=discord.Color.green() if correct else discord.Color.red(),
        )
        if view.round_number < 5:
            view.add_item(TriviaAgainButton())
        else:
            percentage = round(view.score / 5 * 100)
            embed.add_field(
                name="Five-question run complete",
                value=f"Final accuracy: **{percentage}%**",
                inline=False,
            )
            view.stop()
        await _edit_dashboard(interaction, embed, view)


class TriviaAgainButton(discord.ui.Button):
    """Start another reviewed trivia question without rerunning the command."""

    def __init__(self) -> None:
        """Create the replay control on a separate row."""
        super().__init__(label="Another question", row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Replace the result with a fresh question for the same player."""
        old_view = self.view
        if not isinstance(old_view, TriviaView):
            return
        choices = [item for item in TRIVIA_QUESTIONS if item != old_view.question]
        new_view = TriviaView(
            old_view.author_id,
            _pick(choices),
            score=old_view.score,
            round_number=old_view.round_number + 1,
        )
        new_view.message = interaction.message
        old_view.stop()
        await _edit_dashboard(interaction, new_view.embed(), new_view)


class TriviaView(InvokerView):
    """Interactive multiple-choice trivia round."""

    def __init__(
        self,
        author_id: int,
        question: TriviaQuestion,
        *,
        score: int = 0,
        round_number: int = 1,
    ) -> None:
        """Build answer controls for a question."""
        super().__init__(author_id)
        self.question = question
        self.score = score
        self.round_number = round_number
        for index, label in enumerate(question.choices):
            self.add_item(TriviaAnswerButton(index, label))

    def embed(self) -> discord.Embed:
        """Render the unanswered question."""
        return discord.Embed(
            title="Quick trivia",
            description=self.question.prompt,
            color=ACCENT,
        ).set_footer(
            text=f"Question {self.round_number}/5 • Score {self.score} • 90 seconds"
        )


class WouldYouRatherView(discord.ui.View):
    """Public either-or poll with one vote per member and an invoker-owned next button."""

    def __init__(self, author_id: int, prompt: tuple[str, str] | None = None) -> None:
        """Start a public vote hosted by the command invoker."""
        super().__init__(timeout=180)
        self.author_id = author_id
        self.prompt = prompt or _pick(WOULD_YOU_RATHER)
        self.votes: dict[int, str] = {}
        self.message: discord.Message | None = None

    def embed(self) -> discord.Embed:
        """Render the prompt and current live percentages."""
        left = sum(vote == "A" for vote in self.votes.values())
        right = len(self.votes) - left
        total = max(len(self.votes), 1)
        left_units = round(left / total * 10)
        right_units = round(right / total * 10)
        embed = discord.Embed(title="Would you rather?", color=ACCENT)
        embed.add_field(
            name="Option A",
            value=(
                f"{self.prompt[0]}\n`{'█' * left_units}{'░' * (10 - left_units)}` "
                f"**{left / total:.0%}** ({left})"
            ),
            inline=False,
        )
        embed.add_field(
            name="Option B",
            value=(
                f"{self.prompt[1]}\n`{'█' * right_units}{'░' * (10 - right_units)}` "
                f"**{right / total:.0%}** ({right})"
            ),
            inline=False,
        )
        return embed.set_footer(
            text="Everyone may vote once · The host can load the next prompt"
        )

    async def _vote(self, interaction: discord.Interaction, choice: str) -> None:
        if interaction.user.id in self.votes:
            await interaction.response.send_message(
                "You already voted on this prompt.", ephemeral=True
            )
            return
        self.votes[interaction.user.id] = choice
        await _edit_dashboard(interaction, self.embed(), self)

    @discord.ui.button(label="Option A", style=discord.ButtonStyle.primary)
    async def option_a(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Vote for option A."""
        await self._vote(interaction, "A")

    @discord.ui.button(label="Option B", style=discord.ButtonStyle.success)
    async def option_b(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Vote for option B."""
        await self._vote(interaction, "B")

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_prompt(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Let the host advance to a fresh prompt."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the poll host can load the next prompt.", ephemeral=True
            )
            return
        choices = [prompt for prompt in WOULD_YOU_RATHER if prompt != self.prompt]
        self.prompt = _pick(choices)
        self.votes.clear()
        await _edit_dashboard(interaction, self.embed(), self)

    async def on_timeout(self) -> None:
        """Disable voting controls when the poll expires."""
        for item in self.children:
            item.disabled = True
        if self.message:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        """Return a private poll failure without leaving Discord waiting."""
        message = "That vote could not be rendered. Try the command again."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class FunGames(commands.Cog):
    """Lightweight games and conversation starters."""

    fun = app_commands.Group(
        name="fun", description="Play quick games and use conversation starters."
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot instance."""
        self.bot = bot

    @commands.hybrid_command(
        with_app_command=False,
        brief="Flip one or more coins.",
        description="Flip between one and twenty fair virtual coins.",
        usage="[count: 1-20]",
    )
    @commands.cooldown(2, 4, commands.BucketType.user)
    async def coinflip(
        self, ctx: commands.Context, count: commands.Range[int, 1, 20] = 1
    ) -> None:
        """Flip virtual coins."""
        view = ReplayView(ctx.author.id, lambda: _coinflip_embed(count), "Flip again")
        view.message = await _send_dashboard(ctx, _coinflip_embed(count), view=view)

    @commands.hybrid_command(
        with_app_command=False,
        brief="Roll configurable dice.",
        description="Roll up to twenty dice with between two and one thousand sides.",
        usage="[dice: 1-20] [sides: 2-1000]",
    )
    @commands.cooldown(2, 4, commands.BucketType.user)
    async def roll(
        self,
        ctx: commands.Context,
        dice: commands.Range[int, 1, 20] = 1,
        sides: commands.Range[int, 2, 1000] = 6,
    ) -> None:
        """Roll dice and show each result plus its total."""
        view = ReplayView(ctx.author.id, lambda: _dice_embed(dice, sides), "Roll again")
        view.message = await _send_dashboard(ctx, _dice_embed(dice, sides), view=view)

    @commands.hybrid_command(
        with_app_command=False,
        brief="Choose from a list of options.",
        description="Choose one option from a comma- or pipe-separated list.",
        usage="<first, second, third>",
    )
    @commands.cooldown(2, 4, commands.BucketType.user)
    async def choose(self, ctx: commands.Context, *, options: str) -> None:
        """Choose one clean, non-empty option."""
        choices = _options(options)
        view = DecisionView(ctx.author.id, choices)
        view.message = await _send_dashboard(ctx, view.embed(), view=view)

    @commands.hybrid_command(
        with_app_command=False,
        aliases=["8ball"],
        brief="Ask the magic eight ball.",
        description="Ask a complete question and receive a classic eight-ball answer.",
        usage="<question>",
    )
    @commands.cooldown(2, 5, commands.BucketType.user)
    async def eightball(self, ctx: commands.Context, *, question: str) -> None:
        """Answer a sufficiently detailed question."""
        question = question.strip()
        if len(question) < 5:
            raise commands.BadArgument(
                "Ask a complete question (at least 5 characters)."
            )

        def renderer() -> discord.Embed:
            return discord.Embed(
                title="Magic eight ball",
                description=(
                    f"**Q:** {discord.utils.escape_markdown(question[:500])}\n"
                    f"**A:** {_pick(EIGHT_BALL_ANSWERS)}"
                ),
                color=ACCENT,
            )

        view = ReplayView(ctx.author.id, renderer, "Shake again")
        view.message = await _send_dashboard(ctx, renderer(), view=view)

    @commands.hybrid_command(
        with_app_command=False,
        brief="Give something a stable rating.",
        description="Generate a repeatable rating for you and the supplied subject.",
        usage="<subject>",
    )
    async def rate(self, ctx: commands.Context, *, subject: str) -> None:
        """Generate a stable user-specific score without global randomness."""
        subject, score = _rating(ctx.author.id, subject)
        await _send_dashboard(ctx, self._rating_embed(subject, score))

    @commands.hybrid_command(
        with_app_command=False,
        brief="Play rock-paper-scissors.",
        description="Play an interactive first-to-three rock-paper-scissors match.",
        usage="",
    )
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def rps(self, ctx: commands.Context) -> None:
        """Start an interactive rock-paper-scissors round."""
        view = RockPaperScissorsView(ctx.author.id)
        view.message = await _send_dashboard(
            ctx,
            discord.Embed(
                title="Rock, paper, scissors",
                description="First to three wins. Choose your opening move below.",
                color=ACCENT,
            ),
            view=view,
        )

    @commands.hybrid_command(
        with_app_command=False,
        brief="Answer a multiple-choice trivia question.",
        description="Start an interactive, reviewed trivia round.",
        usage="",
    )
    @commands.cooldown(1, 8, commands.BucketType.user)
    async def trivia(self, ctx: commands.Context) -> None:
        """Start one interactive trivia question."""
        view = TriviaView(ctx.author.id, _pick(TRIVIA_QUESTIONS))
        view.message = await _send_dashboard(ctx, view.embed(), view=view)

    @commands.hybrid_command(
        with_app_command=False,
        brief="Measure the stable compatibility between two members.",
        description="Generate a repeatable, playful compatibility score.",
        usage="<first member> [second member]",
    )
    @commands.guild_only()
    @commands.cooldown(2, 5, commands.BucketType.user)
    async def ship(
        self,
        ctx: commands.Context,
        first: discord.Member,
        second: discord.Member | None = None,
    ) -> None:
        """Show a stable, clearly playful compatibility score."""
        second = second or ctx.author
        score = self._ship_score(first.id, second.id)
        await _send_dashboard(ctx, self._ship_embed(first, second, score))

    @commands.hybrid_command(
        with_app_command=False,
        aliases=["wyr"],
        brief="Get a would-you-rather question.",
        description="Start a quick conversation with a reviewed either-or prompt.",
        usage="",
    )
    @commands.cooldown(2, 5, commands.BucketType.user)
    async def wouldyourather(self, ctx: commands.Context) -> None:
        """Send one bounded conversation prompt."""
        view = WouldYouRatherView(ctx.author.id)
        view.message = await _send_dashboard(ctx, view.embed(), view=view)

    @staticmethod
    def _ship_score(first_id: int, second_id: int) -> int:
        pair = ":".join(map(str, sorted((first_id, second_id)))).encode()
        return int.from_bytes(hashlib.blake2b(pair, digest_size=2).digest()) % 101

    @staticmethod
    def _ship_embed(
        first: discord.Member, second: discord.Member, score: int
    ) -> discord.Embed:
        filled = round(score / 10)
        meter = "█" * filled + "░" * (10 - filled)
        chemistry = (score * 7 + 13) % 101
        teamwork = (score * 11 + 29) % 101
        chaos = (score * 17 + 41) % 101
        embed = discord.Embed(
            title="Compatibility check",
            description=(
                f"{first.mention} × {second.mention}\n\n{meter}\n**{score}% compatible**"
            ),
            color=ACCENT,
        )
        embed.add_field(name="Chemistry", value=f"{chemistry}%")
        embed.add_field(name="Teamwork", value=f"{teamwork}%")
        embed.add_field(name="Chaos factor", value=f"{chaos}%")
        return embed.set_footer(
            text="Just for fun — compatibility is not a real measurement."
        )

    @staticmethod
    def _rating_embed(subject: str, score: int) -> discord.Embed:
        filled = round(score / 10)
        verdict = (
            "Certified masterpiece"
            if score >= 90
            else "Strong contender"
            if score >= 70
            else "Respectable"
            if score >= 50
            else "Needs a training arc"
            if score >= 25
            else "Spectacularly questionable"
        )
        return (
            discord.Embed(
                title="Aestron rating lab",
                description=f"**{discord.utils.escape_markdown(subject)}**\n\n{'▰' * filled}{'▱' * (10 - filled)}\n# **{score}/100**",
                color=ACCENT,
            )
            .add_field(name="Verdict", value=verdict)
            .set_footer(text="Stable per user and subject")
        )

    @staticmethod
    @fun.command(name="coinflip", description="Flip between one and twenty coins.")
    @app_commands.checks.cooldown(2, 4, key=lambda interaction: interaction.user.id)
    async def slash_coinflip(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 1, 20] = 1,
    ) -> None:
        """Flip coins through `/fun coinflip`."""
        view = ReplayView(
            interaction.user.id, lambda: _coinflip_embed(count), "Flip again"
        )
        view.message = await _respond_dashboard(
            interaction, _coinflip_embed(count), view=view
        )

    @fun.command(name="roll", description="Roll configurable virtual dice.")
    @app_commands.checks.cooldown(2, 4, key=lambda interaction: interaction.user.id)
    async def slash_roll(
        self,
        interaction: discord.Interaction,
        dice: app_commands.Range[int, 1, 20] = 1,
        sides: app_commands.Range[int, 2, 1000] = 6,
    ) -> None:
        """Roll dice through `/fun roll`."""
        view = ReplayView(
            interaction.user.id, lambda: _dice_embed(dice, sides), "Roll again"
        )
        view.message = await _respond_dashboard(
            interaction, _dice_embed(dice, sides), view=view
        )

    @fun.command(name="choose", description="Choose from comma-separated options.")
    @app_commands.checks.cooldown(2, 4, key=lambda interaction: interaction.user.id)
    async def slash_choose(
        self, interaction: discord.Interaction, options: str
    ) -> None:
        """Choose one supplied option through `/fun choose`."""
        choices = _options(options)
        view = DecisionView(interaction.user.id, choices)
        view.message = await _respond_dashboard(interaction, view.embed(), view=view)

    @fun.command(name="eightball", description="Ask the magic eight ball a question.")
    @app_commands.checks.cooldown(2, 5, key=lambda interaction: interaction.user.id)
    async def slash_eightball(
        self, interaction: discord.Interaction, question: str
    ) -> None:
        """Ask the eight ball through `/fun eightball`."""
        question = question.strip()
        if len(question) < 5:
            raise commands.BadArgument("Ask a complete question of 5+ characters.")

        def renderer() -> discord.Embed:
            return discord.Embed(
                title="Magic eight ball",
                description=(
                    f"**Q:** {discord.utils.escape_markdown(question[:500])}\n"
                    f"**A:** {_pick(EIGHT_BALL_ANSWERS)}"
                ),
                color=ACCENT,
            )

        view = ReplayView(interaction.user.id, renderer, "Shake again")
        view.message = await _respond_dashboard(interaction, renderer(), view=view)

    @fun.command(name="rate", description="Give a subject a stable playful rating.")
    async def slash_rate(self, interaction: discord.Interaction, subject: str) -> None:
        """Rate one subject through `/fun rate`."""
        subject, score = _rating(interaction.user.id, subject)
        await _respond_dashboard(interaction, self._rating_embed(subject, score))

    @fun.command(name="rps", description="Play interactive rock-paper-scissors.")
    @app_commands.checks.cooldown(1, 5, key=lambda interaction: interaction.user.id)
    async def slash_rps(self, interaction: discord.Interaction) -> None:
        """Start rock-paper-scissors through `/fun rps`."""
        view = RockPaperScissorsView(interaction.user.id)
        view.message = await _respond_dashboard(
            interaction,
            discord.Embed(
                title="Rock, paper, scissors",
                description="First to three wins. Choose your opening move below.",
                color=ACCENT,
            ),
            view=view,
        )

    @fun.command(name="trivia", description="Play interactive multiple-choice trivia.")
    @app_commands.checks.cooldown(1, 8, key=lambda interaction: interaction.user.id)
    async def slash_trivia(self, interaction: discord.Interaction) -> None:
        """Start trivia through `/fun trivia`."""
        view = TriviaView(interaction.user.id, _pick(TRIVIA_QUESTIONS))
        view.message = await _respond_dashboard(interaction, view.embed(), view=view)

    @fun.command(name="ship", description="Check two members' playful compatibility.")
    @app_commands.checks.cooldown(2, 5, key=lambda interaction: interaction.user.id)
    async def slash_ship(
        self,
        interaction: discord.Interaction,
        first: discord.Member,
        second: discord.Member | None = None,
    ) -> None:
        """Show compatibility through `/fun ship`."""
        second = second or interaction.user
        score = self._ship_score(first.id, second.id)
        await _respond_dashboard(interaction, self._ship_embed(first, second, score))

    @fun.command(name="would-you-rather", description="Get an either-or prompt.")
    @app_commands.checks.cooldown(2, 5, key=lambda interaction: interaction.user.id)
    async def slash_would_you_rather(self, interaction: discord.Interaction) -> None:
        """Send a conversation prompt through `/fun would-you-rather`."""
        view = WouldYouRatherView(interaction.user.id)
        view.message = await _respond_dashboard(interaction, view.embed(), view=view)
