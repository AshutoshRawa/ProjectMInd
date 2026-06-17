"""
intelligence/intelligence_types.py
===================================
Shared data types for Module 10 — the Autonomous Intelligence Engine.

Keeping types in a separate module prevents circular imports between
pattern_detector, refactor_suggester, and suggestion_store.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Pattern
# ---------------------------------------------------------------------------

PatternType = Literal[
    "GOD_FILE",
    "CIRCULAR_DEPENDENCY",
    "COMPLEXITY_HOTSPOT",
    "ORPHAN_MODULE",
    "SEMANTIC_DUPLICATE",
]

Severity = Literal["critical", "high", "medium", "low"]


@dataclass
class Pattern:
    """
    A detected anti-pattern in the codebase.

    Attributes
    ----------
    pattern_type:
        One of GOD_FILE | CIRCULAR_DEPENDENCY | COMPLEXITY_HOTSPOT |
        ORPHAN_MODULE | SEMANTIC_DUPLICATE.
    severity:
        One of critical | high | medium | low.
    affected_files:
        Relative paths of all files involved in the pattern.
    description:
        Human-readable sentence explaining the pattern.
    evidence:
        List of specific locations (e.g. ``"auth/login.py:42"`` or
        ``"auth/login.py::login"``).
    """

    pattern_type: PatternType
    severity: Severity
    affected_files: list[str]
    description: str
    evidence: list[str] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        """
        A stable, hashable identifier for deduplication.

        Same pattern type + same sorted affected files → same fingerprint.
        """
        key = f"{self.pattern_type}::{':'.join(sorted(self.affected_files))}"
        return key


# ---------------------------------------------------------------------------
# Suggestion
# ---------------------------------------------------------------------------

SuggestionState = Literal["PENDING", "ACCEPTED", "REJECTED", "DEFERRED"]


@dataclass
class Suggestion:
    """
    A refactoring suggestion produced by :mod:`intelligence.refactor_suggester`.

    IMPORTANT: A suggestion is READ-ONLY output — it describes what *could*
    be done.  No code in this project should ever act on a suggestion
    automatically.

    Attributes
    ----------
    id:
        UUID-4 string.  Stable across restarts once persisted.
    pattern_type:
        The anti-pattern this suggestion addresses.
    affected_files:
        Files the suggestion concerns.
    suggestion_text:
        Full plain-English explanation produced by the AI.
    priority:
        1 = critical, 2 = high, 3 = medium.
    state:
        Lifecycle state: PENDING → ACCEPTED | REJECTED | DEFERRED.
    created_at:
        Unix timestamp (float).
    deferred_until:
        Unix timestamp after which a DEFERRED suggestion is re-surfaced.
        Zero if not deferred.
    rejection_reason:
        Free-text reason recorded when a suggestion is rejected.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pattern_type: str = ""
    affected_files: list[str] = field(default_factory=list)
    suggestion_text: str = ""
    priority: int = 3
    state: SuggestionState = "PENDING"
    created_at: float = field(default_factory=time.time)
    deferred_until: float = 0.0
    rejection_reason: str = ""

    def to_dict(self) -> dict:
        """Serialise to a plain dict (JSON-safe)."""
        return {
            "id": self.id,
            "pattern_type": self.pattern_type,
            "affected_files": self.affected_files,
            "suggestion_text": self.suggestion_text,
            "priority": self.priority,
            "state": self.state,
            "created_at": self.created_at,
            "deferred_until": self.deferred_until,
            "rejection_reason": self.rejection_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Suggestion":
        """Reconstruct from a plain dict."""
        return cls(
            id=d["id"],
            pattern_type=d.get("pattern_type", ""),
            affected_files=list(d.get("affected_files", [])),
            suggestion_text=d.get("suggestion_text", ""),
            priority=d.get("priority", 3),
            state=d.get("state", "PENDING"),
            created_at=d.get("created_at", 0.0),
            deferred_until=d.get("deferred_until", 0.0),
            rejection_reason=d.get("rejection_reason", ""),
        )
