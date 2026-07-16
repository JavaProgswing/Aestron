"""Fast, dependency-free games and social commands."""

from __future__ import annotations

import contextlib
import hashlib
import secrets
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

ACCENT = 0xFF4655


def _pick(values: tuple[str, ...] | list[str]) -> str:
    """Choose one value using the operating system random source."""
    return values[secrets.randbelow(len(values))]


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


class RockPaperScissorsView(InvokerView):
    """One-round rock-paper-scissors game."""

    choices = ("rock", "paper", "scissors")
    wins_against = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
    emojis = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}

    async def _play(self, interaction: discord.Interaction, choice: str) -> None:
        bot_choice = _pick(self.choices)
        if choice == bot_choice:
            outcome = "Draw"
            color = discord.Color.gold()
        elif self.wins_against[choice] == bot_choice:
            outcome = "You win!"
            color = discord.Color.green()
        else:
            outcome = "Aestron wins!"
            color = discord.Color.red()
        embed = discord.Embed(
            title=outcome,
            description=(
                f"You chose {self.emojis[choice]} **{choice.title()}**\n"
                f"I chose {self.emojis[bot_choice]} **{bot_choice.title()}**"
            ),
            color=color,
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Rock", emoji="🪨")
    async def rock(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Play rock."""
        await self._play(interaction, "rock")

    @discord.ui.button(label="Paper", emoji="📄")
    async def paper(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Play paper."""
        await self._play(interaction, "paper")

    @discord.ui.button(label="Scissors", emoji="✂️")
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
            title="Correct! 🎉" if correct else "Not quite",
            description=(f"**Answer:** {answer}\n\n{view.question.explanation}"),
            color=discord.Color.green() if correct else discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=view)
        view.stop()


class TriviaView(InvokerView):
    """Interactive multiple-choice trivia round."""

    def __init__(self, author_id: int, question: TriviaQuestion) -> None:
        """Build answer controls for a question."""
        super().__init__(author_id)
        self.question = question
        for index, label in enumerate(question.choices):
            self.add_item(TriviaAnswerButton(index, label))

    def embed(self) -> discord.Embed:
        """Render the unanswered question."""
        return discord.Embed(
            title="Quick trivia 🧠",
            description=self.question.prompt,
            color=ACCENT,
        ).set_footer(text="Choose one answer • 90 seconds")


class FunGames(commands.Cog):
    """Lightweight games and conversation starters."""

    games = app_commands.Group(name="games", description="Interactive Aestron games.")

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
        results = [_pick(("Heads", "Tails")) for _ in range(count)]
        heads = results.count("Heads")
        embed = discord.Embed(
            title="Coin flip 🪙",
            description=" • ".join(results),
            color=ACCENT,
        )
        if count > 1:
            embed.set_footer(text=f"Heads {heads} • Tails {count - heads}")
        await ctx.send(embed=embed)

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
        values = [secrets.randbelow(sides) + 1 for _ in range(dice)]
        await ctx.send(
            embed=discord.Embed(
                title=f"{dice}d{sides} 🎲",
                description=" + ".join(map(str, values)) + f" = **{sum(values)}**",
                color=ACCENT,
            )
        )

    @commands.hybrid_command(
        with_app_command=False,
        brief="Choose from a list of options.",
        description="Choose one option from a comma- or pipe-separated list.",
        usage="<first, second, third>",
    )
    @commands.cooldown(2, 4, commands.BucketType.user)
    async def choose(self, ctx: commands.Context, *, options: str) -> None:
        """Choose one clean, non-empty option."""
        separator = "|" if "|" in options else ","
        choices = [value.strip() for value in options.split(separator) if value.strip()]
        if not 2 <= len(choices) <= 25:
            raise commands.BadArgument("Provide between 2 and 25 options.")
        await ctx.send(f"I choose: **{discord.utils.escape_markdown(_pick(choices))}**")

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
        answers = (
            "It is certain.",
            "Outlook good.",
            "Signs point to yes.",
            "Ask again later.",
            "Cannot predict now.",
            "Don't count on it.",
            "Very doubtful.",
            "My sources say no.",
        )
        await ctx.send(
            embed=discord.Embed(
                title="Magic eight ball 🎱",
                description=f"**Q:** {question[:500]}\n**A:** {_pick(answers)}",
                color=ACCENT,
            )
        )

    @commands.hybrid_command(
        with_app_command=False,
        brief="Give something a stable rating.",
        description="Generate a repeatable rating for you and the supplied subject.",
        usage="<subject>",
    )
    async def rate(self, ctx: commands.Context, *, subject: str) -> None:
        """Generate a stable user-specific score without global randomness."""
        subject = " ".join(subject.split())
        if not 1 <= len(subject) <= 100:
            raise commands.BadArgument("The subject must be 1 to 100 characters long.")
        seed = f"{ctx.author.id}:{subject.casefold()}".encode()
        score = int.from_bytes(hashlib.blake2b(seed, digest_size=2).digest()) % 101
        await ctx.send(
            f"I rate **{discord.utils.escape_markdown(subject)}** **{score}/100**."
        )

    @commands.hybrid_command(
        with_app_command=False,
        brief="Play rock-paper-scissors.",
        description="Open an interactive one-round rock-paper-scissors game.",
        usage="",
    )
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def rps(self, ctx: commands.Context) -> None:
        """Start an interactive rock-paper-scissors round."""
        view = RockPaperScissorsView(ctx.author.id)
        view.message = await ctx.send(
            embed=discord.Embed(
                title="Rock, paper, scissors",
                description="Choose your move below.",
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
        view.message = await ctx.send(embed=view.embed(), view=view)

    @games.command(name="rps", description="Play rock-paper-scissors against Aestron.")
    async def slash_rps(self, interaction: discord.Interaction) -> None:
        """Start rock-paper-scissors from the grouped slash command."""
        view = RockPaperScissorsView(interaction.user.id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Rock, paper, scissors",
                description="Choose your move below.",
                color=ACCENT,
            ),
            view=view,
        )
        view.message = await interaction.original_response()

    @games.command(name="trivia", description="Answer a reviewed trivia question.")
    async def slash_trivia(self, interaction: discord.Interaction) -> None:
        """Start trivia from the grouped slash command."""
        view = TriviaView(interaction.user.id, _pick(TRIVIA_QUESTIONS))
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()
