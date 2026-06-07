"""
graph/
======
Module 6 — Graph Engine.

Builds and maintains an incremental directed dependency graph of the
codebase.  Consumes :class:`~analysis.analysis_types.FileAnalysis`
events and publishes rich graph-update payloads.

This module **never** writes to the Obsidian vault.  Graph data only.
Vault integration is Module 8's responsibility.

Public surface
--------------
- :class:`GraphEngine`         — incremental DiGraph wrapper
- :class:`GraphStateManager`   — save/load with auto-save
- :class:`Module6GraphEngine`  — EventBus service (start/stop)
- :func:`find_orphans`         — isolated nodes
- :func:`find_hubs`            — high in-degree nodes
- :func:`find_circular_deps`   — cycle detection
- :func:`complexity_hotspots`  — risk nodes
- :func:`save_graph`           — convenience persist
- :func:`load_graph`           — convenience restore
"""

from __future__ import annotations

from graph.graph_analyzer import (
    complexity_hotspots,
    find_circular_deps,
    find_hubs,
    find_orphans,
)
from graph.graph_builder import GraphEngine
from graph.graph_engine import Module6GraphEngine
from graph.graph_state import GraphStateManager, load_graph, save_graph

__all__ = [
    # Builder
    "GraphEngine",
    # Persistence
    "GraphStateManager",
    "load_graph",
    "save_graph",
    # Service
    "Module6GraphEngine",
    # Analyser
    "complexity_hotspots",
    "find_circular_deps",
    "find_hubs",
    "find_orphans",
]
