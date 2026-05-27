from __future__ import annotations

import ast


_BASE_DECISION_NODES: tuple[type[ast.AST], ...] = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.ExceptHandler,
    ast.Assert,
    ast.BoolOp,
    ast.comprehension,
)

_OPTIONAL_DECISION_NODES = tuple(
    node_type
    for node_type in (
        getattr(ast, "Match", None),
        getattr(ast, "match_case", None),
    )
    if node_type is not None
)

_DECISION_NODES: tuple[type[ast.AST], ...] = (
    *_BASE_DECISION_NODES,
    *_OPTIONAL_DECISION_NODES,
)


def cyclomatic_complexity(func_node: ast.AST) -> int:
    """
    Approximate cyclomatic complexity for a function node.

    Starts at 1 and increments for common decision points.
    """
    score = 1
    for node in ast.walk(func_node):
        if isinstance(node, ast.BoolOp):
            # `a and b and c` adds (n-1) decision points
            values = getattr(node, "values", None)
            if isinstance(values, list) and len(values) > 1:
                score += len(values) - 1
            continue
        if isinstance(node, _DECISION_NODES):
            score += 1
    return score
