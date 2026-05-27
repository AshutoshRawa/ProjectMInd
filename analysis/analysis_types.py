from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    line_start: int
    line_end: int
    params: list[str]
    complexity: int
    has_docstring: bool
    calls: list[str]


@dataclass(frozen=True)
class FileAnalysis:
    path: str
    language: str
    lines_of_code: int
    functions: list[FunctionInfo]
    classes: list[str]
    imports: list[str]
    ai_summary: str
    anti_patterns: list[str]
    analyzed_at: float  # unix timestamp (seconds)
