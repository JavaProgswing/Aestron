from aestron_bot.fun import (
    FunGames,
    RockPaperScissorsView,
    TriviaView,
    _rating,
)


def test_fun_commands_have_complete_metadata():
    expected = {"coinflip", "roll", "choose", "eightball", "rate", "rps", "trivia"}
    registered = {command.name: command for command in FunGames.__cog_commands__}

    assert expected <= registered.keys()
    for name in expected:
        assert registered[name].brief
        assert registered[name].description
        assert registered[name].usage is not None


def test_rate_is_repeatable_for_a_user_and_subject():
    first_subject, first_score = _rating(123, "clean code")
    second_subject, second_score = _rating(123, "clean   code")

    assert first_subject == second_subject
    assert first_score == second_score
    assert (
        f"{first_score}/100"
        in FunGames._rating_embed(first_subject, first_score).description
    )


def test_interactive_games_are_invoker_scoped():
    rps = RockPaperScissorsView(author_id=123)
    assert rps.author_id == 123
    assert len(rps.children) == 3

    from aestron_bot.fun import TRIVIA_QUESTIONS

    trivia = TriviaView(123, TRIVIA_QUESTIONS[0])
    assert len(trivia.children) == 4
    assert trivia.question.prompt in trivia.embed().description
