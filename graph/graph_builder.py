"""
graph/graph_builder.py
======================
Module 6 — Graph Engine core.

Wraps a :class:`networkx.DiGraph` and provides an **incremental** API:
every mutation touches only the affected node/edges rather than
rebuilding the entire graph from scratch.

Node attributes stored per file path:
    - language     : str
    - complexity   : float  (weighted cyclomatic average from analysis)
    - function_count: int
    - last_analyzed: float  (unix timestamp)

Edges represent import dependencies: an edge ``A → B`` means *A imports B*.
"""

from __future__ import annotations

from typing import Any

import networkx as nx

from analysis.analysis_types import FileAnalysis
from analysis.complexity import file_complexity_score
from core import get_logger

log = get_logger(__name__)


class GraphEngine:
    """Incremental, in-memory directed dependency graph for a codebase.

    The underlying :class:`networkx.DiGraph` is accessible via the
    :attr:`graph` property for read-only inspection by other subsystems
    (e.g. :mod:`graph.graph_analyzer`).

    All mutation methods return ``self`` to allow simple chaining in
    tests, but callers are not expected to use that pattern in production.
    """

    def __init__(self) -> None:
        self._g: nx.DiGraph = nx.DiGraph()

    # ------------------------------------------------------------------
    # Public read-only property
    # ------------------------------------------------------------------

    @property
    def graph(self) -> nx.DiGraph:
        """The raw :class:`networkx.DiGraph`.  Treat as *read-only*."""
        return self._g

    # ------------------------------------------------------------------
    # Mutation — nodes
    # ------------------------------------------------------------------

    def update_node(self, analysis: FileAnalysis) -> GraphEngine:
        """Add or update the node for *analysis.path*.

        **Incremental** — only the single node's attributes are written;
        the rest of the graph is untouched.

        Parameters
        ----------
        analysis:
            The :class:`~analysis.analysis_types.FileAnalysis` snapshot
            to store as graph node attributes.
        """
        path = analysis.path
        attrs: dict[str, Any] = {
            "language": analysis.language,
            "complexity": round(file_complexity_score(analysis), 2),
            "function_count": len(analysis.functions),
            "last_analyzed": analysis.analyzed_at,
        }
        if self._g.has_node(path):
            # Incremental: merge attributes, don't re-add.
            self._g.nodes[path].update(attrs)
        else:
            self._g.add_node(path, **attrs)

        log.debug("[graph] node updated: %s", path)
        return self

    # ------------------------------------------------------------------
    # Mutation — edges
    # ------------------------------------------------------------------

    def update_edges(self, analysis: FileAnalysis) -> tuple[list[str], list[str]]:
        """Sync import edges for *analysis.path*.

        Edges are directed: ``analysis.path → imported_module``.

        Only imports that look like local file paths (i.e. contain a
        ``/`` or are present as nodes) are wired; bare stdlib/third-party
        names are added as *stub* nodes so the graph stays traversable
        without hard-coding language rules.

        Returns
        -------
        tuple[list[str], list[str]]
            ``(edges_added, edges_removed)`` — lists of target paths that
            were added or removed respectively.
        """
        source = analysis.path
        desired = set(analysis.imports)

        # Determine currently wired targets.
        existing_targets: set[str] = {
            tgt for _, tgt in self._g.out_edges(source)
        } if self._g.has_node(source) else set()

        to_add = desired - existing_targets
        to_remove = existing_targets - desired

        for tgt in to_remove:
            self._g.remove_edge(source, tgt)

        for tgt in to_add:
            # Ensure the target node exists (stub if unknown).
            if not self._g.has_node(tgt):
                self._g.add_node(tgt, language="unknown", complexity=0.0,
                                  function_count=0, last_analyzed=0.0, stub=True)
            self._g.add_edge(source, tgt)

        if to_add or to_remove:
            log.debug(
                "[graph] edges for %s: +%d -%d",
                source, len(to_add), len(to_remove),
            )

        return sorted(to_add), sorted(to_remove)

    # ------------------------------------------------------------------
    # Mutation — removal
    # ------------------------------------------------------------------

    def remove_node(self, path: str) -> GraphEngine:
        """Remove *path* and all its incident edges from the graph.

        Safe to call even if *path* is not present.
        """
        if self._g.has_node(path):
            self._g.remove_node(path)
            log.debug("[graph] node removed: %s", path)
        return self

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_neighbors(self, path: str) -> list[str]:
        """Return all nodes directly reachable from *path* (its imports).

        Parameters
        ----------
        path:
            Source file path node.

        Returns
        -------
        list[str]
            Sorted list of direct successor node IDs.
        """
        if not self._g.has_node(path):
            return []
        return sorted(self._g.successors(path))

    def get_related_files(self, path: str, depth: int = 2) -> list[str]:
        """Return all files reachable from *path* within *depth* hops.

        Uses BFS over outgoing edges.  The starting *path* itself is
        excluded from the result.

        Parameters
        ----------
        path:
            Source file path node.
        depth:
            Maximum number of hops to traverse (default 2).

        Returns
        -------
        list[str]
            Sorted list of reachable node IDs (excluding *path*).
        """
        if not self._g.has_node(path):
            return []

        visited: set[str] = set()
        frontier: list[str] = [path]

        for _ in range(depth):
            next_frontier: list[str] = []
            for node in frontier:
                for successor in self._g.successors(node):
                    if successor not in visited and successor != path:
                        visited.add(successor)
                        next_frontier.append(successor)
            frontier = next_frontier

        return sorted(visited)
