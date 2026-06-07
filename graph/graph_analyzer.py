"""
graph/graph_analyzer.py
=======================
Pure analysis functions that operate on a :class:`networkx.DiGraph`
produced by :class:`~graph.graph_builder.GraphEngine`.

All functions are **side-effect-free** — they never mutate the graph.

Terminology
-----------
- **orphan**: a node with no in-edges (nothing imports it) *and* no
  out-edges (it imports nothing) — i.e. an island in the graph.
- **hub**: a node imported by *threshold* or more other nodes (high
  in-degree), indicating a central dependency.
- **circular dependency**: any simple cycle in the directed graph.
- **complexity hotspot**: a node whose complexity is in the top
  quartile *and* whose in-degree is also in the top quartile —
  high-risk, highly-depended-upon code.
"""

from __future__ import annotations

import networkx as nx

from core import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Orphan detection
# ---------------------------------------------------------------------------

def find_orphans(graph: nx.DiGraph) -> list[str]:
    """Return file paths that are neither importing nor imported by anything.

    A node is an orphan if it has **zero** in-edges *and* **zero** out-edges
    (i.e. it is a complete island — no relationships at all).

    Parameters
    ----------
    graph:
        The directed dependency graph.

    Returns
    -------
    list[str]
        Sorted list of orphan node IDs.
    """
    orphans: list[str] = [
        node
        for node in graph.nodes
        if graph.in_degree(node) == 0 and graph.out_degree(node) == 0
    ]
    log.debug("[graph_analyzer] found %d orphan(s)", len(orphans))
    return sorted(orphans)


# ---------------------------------------------------------------------------
# Hub detection
# ---------------------------------------------------------------------------

def find_hubs(graph: nx.DiGraph, threshold: int = 5) -> list[str]:
    """Return file paths imported by *threshold* or more other files.

    A *hub* has high in-degree: many other modules depend on it.

    Parameters
    ----------
    graph:
        The directed dependency graph.
    threshold:
        Minimum in-degree to qualify as a hub (default 5).

    Returns
    -------
    list[str]
        Sorted list of hub node IDs, highest in-degree first.
    """
    hubs: list[str] = [
        node
        for node in graph.nodes
        if graph.in_degree(node) >= threshold
    ]
    # Sort by descending in-degree, then alphabetically for stability.
    hubs.sort(key=lambda n: (-graph.in_degree(n), n))
    log.debug("[graph_analyzer] found %d hub(s) at threshold=%d", len(hubs), threshold)
    return hubs


# ---------------------------------------------------------------------------
# Circular dependency detection
# ---------------------------------------------------------------------------

def find_circular_deps(graph: nx.DiGraph) -> list[list[str]]:
    """Return all simple cycles in the dependency graph.

    Uses :func:`networkx.simple_cycles` which implements Johnson's
    algorithm (O((n+e)(c+1)) for *c* cycles).

    Parameters
    ----------
    graph:
        The directed dependency graph.

    Returns
    -------
    list[list[str]]
        List of cycles.  Each cycle is a list of node IDs in traversal
        order (the last node's successor is the first node to close the
        cycle).  Sorted for deterministic output.
    """
    raw_cycles: list[list[str]] = list(nx.simple_cycles(graph))
    # Normalise each cycle: rotate so the alphabetically smallest node
    # comes first, then sort the list of cycles.
    normalised: list[list[str]] = []
    for cycle in raw_cycles:
        if not cycle:
            continue
        min_idx = cycle.index(min(cycle))
        rotated = cycle[min_idx:] + cycle[:min_idx]
        normalised.append(rotated)
    normalised.sort()
    log.debug("[graph_analyzer] found %d cycle(s)", len(normalised))
    return normalised


# ---------------------------------------------------------------------------
# Complexity hotspots
# ---------------------------------------------------------------------------

def complexity_hotspots(graph: nx.DiGraph) -> list[str]:
    """Return nodes that are both high-complexity *and* heavily depended-upon.

    A *hotspot* is a node whose ``complexity`` attribute is in the **top
    quartile** of all node complexities *and* whose in-degree is in the
    **top quartile** of all in-degrees.

    Nodes without a ``complexity`` attribute (e.g. stub nodes for external
    imports) are excluded.

    Parameters
    ----------
    graph:
        The directed dependency graph.

    Returns
    -------
    list[str]
        Sorted list of hotspot node IDs, ordered by descending
        ``complexity * in_degree`` score.
    """
    # Gather real nodes (those with a complexity attribute).
    candidates: list[tuple[str, float, int]] = []
    for node, attrs in graph.nodes(data=True):
        complexity = attrs.get("complexity")
        if complexity is None:
            continue
        candidates.append((node, float(complexity), graph.in_degree(node)))

    if not candidates:
        return []

    complexities = [c for _, c, _ in candidates]
    in_degrees = [d for _, _, d in candidates]

    q75_complexity = _quartile(complexities, 75)
    q75_in_degree = _quartile(in_degrees, 75)

    hotspots: list[tuple[str, float]] = [
        (node, complexity * in_degree)
        for node, complexity, in_degree in candidates
        if complexity > q75_complexity and in_degree > q75_in_degree
    ]
    # Sort by descending score, then alphabetically.
    hotspots.sort(key=lambda t: (-t[1], t[0]))
    result = [node for node, _ in hotspots]
    log.debug("[graph_analyzer] found %d hotspot(s)", len(result))
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _quartile(values: list[float], pct: int) -> float:
    """Return the *pct*-th percentile of *values* using linear interpolation."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    idx = (pct / 100) * (n - 1)
    lower = int(idx)
    upper = lower + 1
    if upper >= n:
        return float(sorted_vals[-1])
    fraction = idx - lower
    return sorted_vals[lower] + fraction * (sorted_vals[upper] - sorted_vals[lower])
