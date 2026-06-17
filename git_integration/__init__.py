"""
git/
====
**Module 9 — Git Intelligence Engine**

Monitors a git repository for new commits, generates AI-powered summaries,
and stores them in the semantic memory store (M7) for later retrieval.

Public API
----------
- :class:`~git.git_types.CommitInfo`       — commit data container
- :class:`~git.git_types.DiffChunk`        — per-file diff fragment
- :class:`~git.git_monitor.GitMonitor`     — polls HEAD every 30 s
- :func:`~git.commit_summarizer.summarize` — hierarchical AI summariser
- :func:`~git.commit_summarizer.calculate_impact_score` — 0–1 impact metric
- :class:`~git.git_memory.GitMemory`       — M7 storage + commit search
- :class:`~git.git_engine.GitEngine`       — event-driven orchestrator

Event contracts
---------------
Subscribes to:
    ``git.commit`` — published by :class:`~git.git_monitor.GitMonitor`

Publishes:
    ``git.commit_summarized`` — enriched :class:`~git.git_types.CommitInfo`
"""

from __future__ import annotations

from git_integration.commit_summarizer import calculate_impact_score, summarize
from git_integration.git_engine import GitEngine
from git_integration.git_memory import GitMemory
from git_integration.git_monitor import GitMonitor
from git_integration.git_types import CommitInfo, DiffChunk

__all__ = [
    "CommitInfo",
    "DiffChunk",
    "GitEngine",
    "GitMemory",
    "GitMonitor",
    "calculate_impact_score",
    "summarize",
]
