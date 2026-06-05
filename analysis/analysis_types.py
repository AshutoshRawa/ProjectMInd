"""
analysis/analysis_types.py
==========================
Core data structures for code analysis results.

Both :class:`FunctionInfo` and :class:`FileAnalysis` are frozen dataclasses
with full JSON round-trip support via ``to_dict``/``from_dict`` and
``to_json``/``from_json`` helpers.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class FunctionInfo:
    """Structured metadata for a single function or method."""

    name: str
    line_start: int
    line_end: int
    params: list[str]
    complexity: int  # cyclomatic
    has_docstring: bool
    calls: list[str]  # function names called inside

    # ------------------------------------------------------------------
    # JSON serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict representation suitable for JSON encoding."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FunctionInfo:
        """Reconstruct a :class:`FunctionInfo` from a dict."""
        return cls(
            name=data["name"],
            line_start=data["line_start"],
            line_end=data["line_end"],
            params=list(data.get("params", [])),
            complexity=data.get("complexity", 1),
            has_docstring=data.get("has_docstring", False),
            calls=list(data.get("calls", [])),
        )

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, s: str) -> FunctionInfo:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(s))


@dataclass(frozen=True)
class FileAnalysis:
    """Complete analysis result for a single source file."""

    path: str
    language: str
    lines_of_code: int
    functions: list[FunctionInfo]
    classes: list[str]
    imports: list[str]
    ai_summary: str  # from AI engine
    anti_patterns: list[str]
    analyzed_at: float  # unix timestamp (seconds)

    # ------------------------------------------------------------------
    # JSON serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict representation suitable for JSON encoding."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileAnalysis:
        """Reconstruct a :class:`FileAnalysis` from a dict.

        Nested ``functions`` entries are rebuilt as :class:`FunctionInfo`
        instances rather than left as raw dicts.
        """
        raw_functions = data.get("functions", [])
        functions = [
            FunctionInfo.from_dict(f) if isinstance(f, dict) else f
            for f in raw_functions
        ]
        return cls(
            path=data["path"],
            language=data.get("language", "unknown"),
            lines_of_code=data.get("lines_of_code", 0),
            functions=functions,
            classes=list(data.get("classes", [])),
            imports=list(data.get("imports", [])),
            ai_summary=data.get("ai_summary", ""),
            anti_patterns=list(data.get("anti_patterns", [])),
            analyzed_at=data.get("analyzed_at", 0.0),
        )

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, s: str) -> FileAnalysis:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(s))
