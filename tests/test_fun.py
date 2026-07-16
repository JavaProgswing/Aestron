import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aestron_bot.fun import FunGames, RockPaperScissorsView, TriviaView


def test_fun_commands_have_complete_metadata():
    expected = {"coinflip", "roll", "choose", "eightball", "rate", "rps", "trivia"}
    registered = {command.name: command for command in FunGames.__cog_commands__}

    assert expected <= registered.keys()
    for name in expected:
        assert registered[name].brief
        assert registered[name].description
        assert registered[name].usage is not None


def test_rate_is_repeatable_for_a_user_and_subject():
    async def run_test():
        cog = FunGames(SimpleNamespace())
        ctx = SimpleNamespace(author=SimpleNamespace(id=123), send=AsyncMock())

        await FunGames.rate.callback(cog, ctx, subject="clean code")
        first = ctx.send.await_args.args[0]
        await FunGames.rate.callback(cog, ctx, subject="clean   code")
        second = ctx.send.await_args.args[0]

        assert first == second
        assert "/100" in first

    asyncio.run(run_test())


def test_interactive_games_are_invoker_scoped():
    rps = RockPaperScissorsView(author_id=123)
    assert rps.author_id == 123
    assert len(rps.children) == 3

    from aestron_bot.fun import TRIVIA_QUESTIONS

    trivia = TriviaView(123, TRIVIA_QUESTIONS[0])
    assert len(trivia.children) == 4
    assert trivia.question.prompt in trivia.embed().description
