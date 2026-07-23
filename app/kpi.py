"""Config-driven KPI engine.

KPIs are stored as small arithmetic expressions (see db.kpi_definitions)
referencing a fixed set of scope variables:
  total_sales_volume, total_sales_value, num_stores, num_skus, num_weeks

Expressions are evaluated with a restricted AST walker (+ - * / ( ) and
numeric literals/names only) rather than Python's eval, so a typo or a
pasted formula can't execute arbitrary code.
"""

from __future__ import annotations

import ast
import operator

ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
ALLOWED_UNARYOPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}


class KpiError(ValueError):
    pass


def _eval_node(node, variables: dict):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, variables)
    if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_BINOPS:
        left = _eval_node(node.left, variables)
        right = _eval_node(node.right, variables)
        if isinstance(node.op, ast.Div) and right == 0:
            raise KpiError("Division by zero")
        return ALLOWED_BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_UNARYOPS:
        return ALLOWED_UNARYOPS[type(node.op)](_eval_node(node.operand, variables))
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise KpiError(f"Unknown variable '{node.id}'")
        return variables[node.id]
    raise KpiError(f"Unsupported expression element: {ast.dump(node)}")


def evaluate_kpi(expression: str, variables: dict) -> float:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise KpiError(f"Invalid expression syntax: {e}") from e
    return _eval_node(tree, variables)


def validate_expression(expression: str) -> str | None:
    """Return an error message if the expression is invalid, else None."""
    dummy_vars = {
        "total_sales_volume": 1.0,
        "total_sales_value": 1.0,
        "store_sales_volume": 1.0,
        "store_sales_value": 1.0,
        "num_stores": 1.0,
        "num_skus": 1.0,
        "num_weeks": 1.0,
    }
    try:
        evaluate_kpi(expression, dummy_vars)
    except KpiError as e:
        return str(e)
    return None
