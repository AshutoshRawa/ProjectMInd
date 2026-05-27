from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from analysis.analysis_types import FileAnalysis, FunctionInfo
from analysis.complexity import cyclomatic_complexity


@dataclass(frozen=True)
class AstExtract:
    language: str
    lines_of_code: int
    functions: list[FunctionInfo]
    classes: list[str]
    imports: list[str]


def analyze_python(path: Path, source: str) -> AstExtract:
    """
    Extract structural info for a Python file using `ast`.

    On SyntaxError, returns a partial result (imports/classes/functions empty)
    but still reports language and LoC.
    """
    loc = _lines_of_code(source)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return AstExtract(
            language="python",
            lines_of_code=loc,
            functions=[],
            classes=[],
            imports=[],
        )

    classes: list[str] = []
    functions: list[FunctionInfo] = []
    imports: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_function_info(node))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.extend(_import_entries(node))

    # Also discover nested functions (common in Python codebases).
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node not in tree.body:
            # Skip if already captured as top-level.
            info = _function_info(node)
            if all(f.name != info.name or f.line_start != info.line_start for f in functions):
                functions.append(info)

    return AstExtract(
        language="python",
        lines_of_code=loc,
        functions=sorted(functions, key=lambda f: (f.line_start, f.name)),
        classes=sorted(set(classes)),
        imports=sorted(set(imports)),
    )


def empty_extract(*, language: str, source: str) -> AstExtract:
    return AstExtract(
        language=language,
        lines_of_code=_lines_of_code(source),
        functions=[],
        classes=[],
        imports=[],
    )


def _lines_of_code(source: str) -> int:
    return sum(1 for line in source.splitlines() if line.strip())


def _function_info(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionInfo:
    params = [a.arg for a in node.args.args]
    if node.args.vararg is not None:
        params.append(f"*{node.args.vararg.arg}")
    params.extend([a.arg for a in node.args.kwonlyargs])
    if node.args.kwarg is not None:
        params.append(f"**{node.args.kwarg.arg}")

    calls = sorted(set(_collect_calls(node)))
    has_doc = ast.get_docstring(node) is not None
    line_start = int(getattr(node, "lineno", 1) or 1)
    line_end = int(getattr(node, "end_lineno", line_start) or line_start)
    complexity = cyclomatic_complexity(node)

    return FunctionInfo(
        name=node.name,
        line_start=line_start,
        line_end=line_end,
        params=params,
        complexity=complexity,
        has_docstring=has_doc,
        calls=calls,
    )


def _collect_calls(func_node: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                names.append(fn.id)
            elif isinstance(fn, ast.Attribute):
                names.append(fn.attr)
    return names


def _import_entries(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        out: list[str] = []
        for alias in node.names:
            out.append(alias.name)
        return out

    # ImportFrom
    module = node.module or ""
    out = []
    for alias in node.names:
        if module:
            out.append(f"{module}.{alias.name}")
        else:
            out.append(alias.name)
    return out
