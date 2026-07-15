"""Calculator safety and behavior tests."""

import pytest

from aestron_bot.calculator import evaluate_expression


def test_calculator_handles_arithmetic_and_precedence():
    assert evaluate_expression("2 + 3 * (4 - 1)") == 11
    assert evaluate_expression("7 / 2") == 3.5


@pytest.mark.parametrize(
    "expression",
    (
        "__import__('os').getcwd()",
        "value = 4",
        "2 ** 1000",
        "1 / 0",
    ),
)
def test_calculator_rejects_unsafe_or_unbounded_expressions(expression):
    with pytest.raises(ValueError):
        evaluate_expression(expression)
