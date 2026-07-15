"""Bounded arithmetic expression evaluation for the calculator command."""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable

Number = int | float

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[Number, Number], Number]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[Number], Number]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def evaluate_expression(expression: str) -> Number:
    """Evaluate a numeric expression without names, calls, or arbitrary code."""
    if not expression.strip():
        raise ValueError("Enter an arithmetic expression.")
    if len(expression) > 200:
        raise ValueError("The expression is too long.")
    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise ValueError("The expression has invalid syntax.") from error
    return _evaluate_node(parsed.body, depth=0)


def _evaluate_node(node: ast.AST, *, depth: int) -> Number:
    if depth > 32:
        raise ValueError("The expression is too deeply nested.")
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        value = _evaluate_node(node.operand, depth=depth + 1)
        return _bounded(_UNARY_OPERATORS[type(node.op)](value))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_node(node.left, depth=depth + 1)
        right = _evaluate_node(node.right, depth=depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > 12:
            raise ValueError("Exponents must be between -12 and 12.")
        try:
            return _bounded(_BINARY_OPERATORS[type(node.op)](left, right))
        except ZeroDivisionError as error:
            raise ValueError("Division by zero is not allowed.") from error
        except OverflowError as error:
            raise ValueError("The result is too large.") from error
    raise ValueError("Only numbers and arithmetic operators are allowed.")


def _bounded(value: Number) -> Number:
    if abs(value) > 1e100:
        raise ValueError("The result is too large.")
    return value
