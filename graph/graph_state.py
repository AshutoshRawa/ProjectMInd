"""
graph/graph_state.py
====================
Persist and restore the in-memory :class:`networkx.DiGraph` to/from a
JSON file using networkx's *node-link* format.

Design decisions
----------------
- **Auto-save**: a counter tracks mutations.  After every 10 updates
  the graph is persisted automatically.  This avoids I/O on every
  single change while still providing reasonable durability.
- **Load failure**: if the file is missing or corrupt we start fresh
  and log a warning rather than crashing — resilience over strictness.
- **Atomic write**: the JSON is written to a ``.tmp`` sibling file and
  then renamed so a crash mid-write never produces a corrupt state file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import networkx as nx
from networkx.readwrite import json_graph

from core import get_logger

log = get_logger(__name__)

# How many update() calls trigger an auto-save.
_AUTO_SAVE_INTERVAL: int = 10


class GraphStateManager:
    """Manages serialisation of a :class:`networkx.DiGraph` to disk.

    Parameters
    ----------
    state_path:
        Absolute path to the ``graph_state.json`` file.
    auto_save_interval:
        Number of :meth:`record_update` calls before an automatic
        :meth:`save_graph` is triggered.
    """

    def __init__(
        self,
        state_path: str | Path,
        auto_save_interval: int = _AUTO_SAVE_INTERVAL,
    ) -> None:
        self._path = Path(state_path)
        self._auto_save_interval = auto_save_interval
        self._update_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_graph(self, graph: nx.DiGraph) -> None:
        """Persist *graph* to :attr:`state_path` atomically.

        Uses a ``.tmp`` sibling + ``os.replace`` so a crash mid-write
        cannot corrupt the existing state file.
        """
        data: dict[str, Any] = json_graph.node_link_data(graph)
        tmp_path = self._path.with_suffix(".tmp")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp_path, self._path)

        log.debug("[graph_state] saved %d nodes to %s", graph.number_of_nodes(), self._path)

    def load_graph(self) -> nx.DiGraph:
        """Load and return the graph from :attr:`state_path`.

        If the file is absent or unparseable a fresh empty
        :class:`~networkx.DiGraph` is returned and a warning is logged.
        """
        if not self._path.exists():
            log.debug("[graph_state] no state file at %s — starting fresh", self._path)
            return nx.DiGraph()

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            graph: nx.DiGraph = json_graph.node_link_graph(raw, directed=True, multigraph=False)
            log.info(
                "[graph_state] loaded %d nodes, %d edges from %s",
                graph.number_of_nodes(), graph.number_of_edges(), self._path,
            )
            return graph
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "[graph_state] failed to load %s (%s) — starting fresh",
                self._path, exc,
            )
            return nx.DiGraph()

    def record_update(self, graph: nx.DiGraph) -> bool:
        """Increment the mutation counter; auto-save every N updates.

        Parameters
        ----------
        graph:
            The current graph — passed in so this manager stays stateless
            with respect to the graph object itself.

        Returns
        -------
        bool
            ``True`` if an auto-save was triggered this call.
        """
        self._update_count += 1
        if self._update_count % self._auto_save_interval == 0:
            self.save_graph(graph)
            return True
        return False

    @property
    def update_count(self) -> int:
        """Total number of updates recorded since construction."""
        return self._update_count

    @property
    def state_path(self) -> Path:
        """Resolved path to the backing JSON file."""
        return self._path


# ---------------------------------------------------------------------------
# Module-level convenience wrappers (satisfy the spec's function signatures)
# ---------------------------------------------------------------------------

def save_graph(graph: nx.DiGraph, path: str | Path) -> None:
    """Persist *graph* to *path*.  Convenience wrapper around :class:`GraphStateManager`."""
    GraphStateManager(path).save_graph(graph)


def load_graph(path: str | Path) -> nx.DiGraph:
    """Load and return graph from *path*.  Convenience wrapper around :class:`GraphStateManager`."""
    return GraphStateManager(path).load_graph()
