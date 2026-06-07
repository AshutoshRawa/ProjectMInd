"""
graph/graph_engine.py
=====================
Module 6 long-lived service.

Subscribes to ``analysis.file_analyzed`` on the :class:`core.EventBus`,
updates the in-memory graph, and publishes ``graph.graph_updated`` with
rich diff metadata.

This service **never** touches the Obsidian vault.  Graph data only.

Published payload shape::

    {
        "updated_node": str,           # file path that changed
        "edges_added":  list[str],     # newly wired import targets
        "edges_removed": list[str],    # de-wired import targets
        "stats": {
            "node_count":  int,
            "edge_count":  int,
            "orphan_count": int,
        },
    }
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any

from analysis.analysis_types import FileAnalysis
from core import EventBus, GraphBuilder, get_config, get_logger
from graph.graph_analyzer import find_orphans
from graph.graph_builder import GraphEngine
from graph.graph_state import GraphStateManager

log = get_logger(__name__)

_DEFAULT_STATE_FILENAME = "graph_state.json"


class Module6GraphEngine(GraphBuilder):
    """Long-lived graph service for Module 6.

    Lifecycle
    ---------
    1. ``start()`` loads existing graph state from disk, then
       subscribes to ``analysis.file_analyzed``.
    2. Each analysis event updates the graph (node + edges) and
       publishes a ``graph.graph_updated`` event.
    3. Auto-save is handled by :class:`~graph.graph_state.GraphStateManager`
       every 10 updates.
    4. ``stop()`` forces a final save, unsubscribes, and joins the
       worker thread.
    """

    name = "graph"

    def __init__(
        self,
        *,
        bus: EventBus,
        state_path: str | Path | None = None,
        input_event: str = "analysis.file_analyzed",
        output_event: str = "graph.graph_updated",
        auto_save_interval: int = 10,
    ) -> None:
        self._bus = bus
        self._input_event = input_event
        self._output_event = output_event

        # Resolve state file path.
        if state_path is None:
            try:
                cfg = get_config()
                project_root = Path(cfg.vault.path).parent
            except Exception:  # noqa: BLE001
                project_root = Path.cwd()
            state_path = project_root / _DEFAULT_STATE_FILENAME

        self._engine = GraphEngine()
        self._state_mgr = GraphStateManager(state_path, auto_save_interval=auto_save_interval)

        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._bus_handler: Any | None = None
        self._started = False

    # ------------------------------------------------------------------
    # Service lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True

        # Restore persisted graph.
        restored = self._state_mgr.load_graph()
        self._engine._g = restored  # type: ignore[attr-defined]  # deliberate internal access

        self._stop_event.clear()
        self._queue = queue.Queue()

        def _on_analysis(payload: dict[str, Any]) -> None:
            self._queue.put(payload)

        self._bus_handler = _on_analysis
        self._bus.subscribe(self._input_event, _on_analysis)

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="projectmind.module6.graph",
            daemon=True,
        )
        self._worker_thread.start()
        log.info("[graph] subscribed to %s, graph has %d node(s)",
                 self._input_event, self._engine.graph.number_of_nodes())

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False

        self._stop_event.set()

        if self._bus_handler is not None:
            self._bus.unsubscribe(self._input_event, self._bus_handler)
            self._bus_handler = None

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=5.0)
            self._worker_thread = None

        # Final save on shutdown.
        self._state_mgr.save_graph(self._engine.graph)
        log.info("[graph] stopped — final save complete")

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                payload = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._process(payload)
            except Exception as exc:  # noqa: BLE001
                log.exception("[graph] error processing analysis: %s", exc)

    def _process(self, payload: dict[str, Any]) -> None:
        analysis_raw = payload.get("analysis")
        if analysis_raw is None:
            return
        file_path: str = payload.get("file_path", "")

        if isinstance(analysis_raw, dict):
            analysis = FileAnalysis.from_dict(analysis_raw)
        elif isinstance(analysis_raw, FileAnalysis):
            analysis = analysis_raw
        else:
            return

        # Incremental graph update.
        self._engine.update_node(analysis)
        edges_added, edges_removed = self._engine.update_edges(analysis)

        # Auto-save every N updates.
        self._state_mgr.record_update(self._engine.graph)

        # Build stats snapshot.
        g = self._engine.graph
        stats: dict[str, int] = {
            "node_count": g.number_of_nodes(),
            "edge_count": g.number_of_edges(),
            "orphan_count": len(find_orphans(g)),
        }

        self._bus.publish(
            self._output_event,
            {
                "updated_node": file_path,
                "edges_added": edges_added,
                "edges_removed": edges_removed,
                "stats": stats,
            },
        )
