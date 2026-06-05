from __future__ import annotations

import ast

from analysis.analysis_types import FileAnalysis


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


def file_complexity_score(analysis: FileAnalysis) -> float:
    """Weighted average cyclomatic complexity across all functions.

    Each function's complexity is weighted by its length (number of
    lines) so that larger, more complex functions dominate the score.

    Returns ``0.0`` when the analysis contains no functions.
    """
    if not analysis.functions:
        return 0.0

    total_weight = 0
    weighted_sum = 0.0
    for func in analysis.functions:
        weight = max(func.line_end - func.line_start + 1, 1)
        weighted_sum += func.complexity * weight
        total_weight += weight

    return weighted_sum / total_weight if total_weight else 0.0
