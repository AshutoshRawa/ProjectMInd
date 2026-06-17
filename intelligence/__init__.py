"""
intelligence/
=============
**Module 10 — Autonomous Intelligence Engine**

Fuses outputs from analysis (M4), graph (M6), and memory (M7) into
self-improving refactoring suggestions backed by a feedback loop.

Architecture
------------
.. code-block:: text

    graph.graph_updated ──► IntelligenceEngine ──► detect_anti_patterns
                                   │                      │
                      (every 60 min)│                      ▼
                                   │              [Pattern list]
                                   │                      │
                                   └──► refactor_suggester.suggest()
                                               │ (read-only AI call)
                                               ▼
                                         [Suggestion]
                                               │
                                    suggestion_store.persist()
                                               │
                                    MemoryStore feedback chunk
                                               │
                              intelligence.suggestions_ready ──► subscribers

Public surface
--------------
.. code-block:: python

    from intelligence import (
        # Detection
        detect_anti_patterns,
        Pattern,
        # Suggestion generation (advisory only — no writes)
        suggest,
        Suggestion,
        # Persistence & feedback loop
        SuggestionStore,
        # Orchestration
        IntelligenceEngine,
    )

Boundary contract
-----------------
``refactor_suggester`` is the only module that calls the AI for this layer.
It **never** writes to files, git, or the vault.  All persistence is
handled exclusively by ``suggestion_store``.
"""

from __future__ import annotations

from intelligence.intelligence_engine import IntelligenceEngine
from intelligence.intelligence_types import Pattern, PatternType, Severity, Suggestion, SuggestionState
from intelligence.pattern_detector import detect_anti_patterns
from intelligence.refactor_suggester import suggest
from intelligence.suggestion_store import SuggestionStore

__all__ = [
    # Types
    "Pattern",
    "PatternType",
    "Severity",
    "Suggestion",
    "SuggestionState",
    # Detection
    "detect_anti_patterns",
    # Suggestion generation (read-only)
    "suggest",
    # Persistence
    "SuggestionStore",
    # Orchestration
    "IntelligenceEngine",
]
