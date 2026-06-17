"""
intelligence/intelligence_engine.py
=====================================
Module 10 — Autonomous Intelligence Engine (long-lived service).

Responsibilities
----------------
1. **Periodic analysis cycle** (every 60 minutes, or on ``graph.graph_updated``
   event): detect anti-patterns → generate suggestions → persist → publish.
2. **Deduplication**: only generate suggestions for patterns that do not already
   have a ``PENDING`` suggestion (checked via :meth:`~SuggestionStore.get_pending`
   pattern fingerprint comparison).
3. **Event publishing**: publishes ``intelligence.suggestions_ready`` with a
   ``{"suggestions": [...]}`` payload after each cycle that produces new items.
4. **CLI query handler**: :meth:`query_codebase` accepts a natural-language
   question, retrieves relevant memory chunks, and sends the assembled context
   to the AI for a grounded answer.

Lifecycle
---------
``start()``
    Subscribe to ``graph.graph_updated``, launch the 60-minute periodic timer
    thread, and restore the graph + analyses from the provided services.

``stop()``
    Signal the timer thread to exit, unsubscribe from the event bus, and
    wait for the worker thread to join (timeout 5 s).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core import EventBus, get_logger
from intelligence.intelligence_types import Pattern, Suggestion
from intelligence.pattern_detector import detect_anti_patterns
from intelligence.refactor_suggester import suggest
from intelligence.suggestion_store import SuggestionStore

if TYPE_CHECKING:
    import networkx as nx

    from analysis.analysis_types import FileAnalysis
    from memory.memory_store import MemoryStore

log = get_logger(__name__)

_CYCLE_INTERVAL_SECONDS: int = 60 * 60  # 60 minutes
_INPUT_EVENT = "graph.graph_updated"
_OUTPUT_EVENT = "intelligence.suggestions_ready"


# ---------------------------------------------------------------------------
# IntelligenceEngine
# ---------------------------------------------------------------------------

class IntelligenceEngine:
    """Long-lived service for Module 10.

    Parameters
    ----------
    bus:
        The process-wide :class:`~core.event_bus.EventBus`.
    graph:
        A live :class:`networkx.DiGraph` reference from Module 6.  Updated
        externally; the engine always reads the latest state.
    analyses:
        A mutable list of :class:`~analysis.analysis_types.FileAnalysis`
        snapshots from Module 4.  The engine iterates this at cycle time.
    store:
        The :class:`~intelligence.suggestion_store.SuggestionStore` instance.
    memory_store:
        Optional :class:`~memory.memory_store.MemoryStore` passed to
        :func:`~intelligence.pattern_detector.detect_anti_patterns` for
        ``SEMANTIC_DUPLICATE`` detection.
    cycle_interval:
        Seconds between periodic analysis cycles.  Defaults to 3 600 (1 h).
    """

    name = "intelligence"

    def __init__(
        self,
        *,
        bus: EventBus,
        graph: "nx.DiGraph",
        analyses: "list[FileAnalysis]",
        store: SuggestionStore,
        memory_store: "MemoryStore | None" = None,
        cycle_interval: int = _CYCLE_INTERVAL_SECONDS,
    ) -> None:
        self._bus = bus
        self._graph = graph
        self._analyses = analyses
        self._store = store
        self._memory_store = memory_store
        self._cycle_interval = cycle_interval

        self._stop_event = threading.Event()
        self._cycle_queue: queue.Queue[bool] = queue.Queue()
        self._timer_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._bus_handler: Any | None = None
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the intelligence engine."""
        if self._started:
            return
        self._started = True
        self._stop_event.clear()

        # Subscribe to graph updates for event-driven triggering.
        # The handler only enqueues a sentinel so the dispatch thread is
        # never blocked by the (potentially slow) analysis cycle.
        def _on_graph_updated(payload: dict[str, Any]) -> None:  # noqa: ANN001
            log.debug("[intelligence_engine] graph.graph_updated received — queuing cycle")
            self._cycle_queue.put(True)

        self._bus_handler = _on_graph_updated
        self._bus.subscribe(_INPUT_EVENT, _on_graph_updated)

        # Worker thread: drains the cycle queue.
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="projectmind.module10.intelligence.worker",
            daemon=True,
        )
        self._worker_thread.start()

        # Periodic background timer.
        self._timer_thread = threading.Thread(
            target=self._timer_loop,
            name="projectmind.module10.intelligence",
            daemon=True,
        )
        self._timer_thread.start()

        log.info(
            "[intelligence_engine] started — cycle_interval=%ds, subscribed to %s",
            self._cycle_interval, _INPUT_EVENT,
        )

    def stop(self) -> None:
        """Stop the intelligence engine gracefully."""
        if not self._started:
            return
        self._started = False
        self._stop_event.set()

        if self._bus_handler is not None:
            self._bus.unsubscribe(_INPUT_EVENT, self._bus_handler)
            self._bus_handler = None

        # Wake the worker so it notices the stop event.
        self._cycle_queue.put(False)

        if self._timer_thread is not None:
            self._timer_thread.join(timeout=5.0)
            self._timer_thread = None

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=5.0)
            self._worker_thread = None

        log.info("[intelligence_engine] stopped")

    # ------------------------------------------------------------------
    # CLI query handler
    # ------------------------------------------------------------------

    def query_codebase(self, question: str) -> str:
        """Answer *question* using semantic memory + AI.

        The method:
        1. Searches the memory store for chunks relevant to *question*.
        2. Assembles them into a grounded context block.
        3. Sends the block + question to the AI via ``complete_raw``.

        Parameters
        ----------
        question:
            Natural-language question about the codebase.

        Returns
        -------
        str
            AI-generated answer grounded in the retrieved context.
        """
        if not question.strip():
            return "Please provide a non-empty question."

        context_lines: list[str] = []

        if self._memory_store is not None:
            try:
                from memory.semantic_search import search

                hits = search(question, store=self._memory_store, top_k=8)
                for hit in hits:
                    context_lines.append(
                        f"[{hit.file_path} | score={hit.score:.2f}]\n{hit.content}"
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("[intelligence_engine] semantic search failed: %s", exc)

        context_block = (
            "\n\n---\n\n".join(context_lines)
            if context_lines
            else "(no relevant context found in memory store)"
        )

        prompt = (
            f"You are a developer assistant for this codebase.\n\n"
            f"## Retrieved context\n\n{context_block}\n\n"
            f"## Question\n\n{question}\n\n"
            f"Answer concisely, referencing the context above where relevant."
        )

        try:
            from ai.ai_manager import get_ai

            answer = get_ai().complete_raw(prompt)
        except Exception as exc:  # noqa: BLE001
            log.error("[intelligence_engine] query AI call failed: %s", exc)
            answer = f"(AI unavailable: {exc})"

        return answer

    # ------------------------------------------------------------------
    # Internal cycle logic
    # ------------------------------------------------------------------

    def _timer_loop(self) -> None:
        """Background loop: sleep for ``_cycle_interval``, then enqueue a cycle."""
        while not self._stop_event.is_set():
            interrupted = self._stop_event.wait(timeout=self._cycle_interval)
            if interrupted:
                break
            self._cycle_queue.put(True)

    def _worker_loop(self) -> None:
        """Drain the cycle queue; run one analysis cycle per item.

        The queue contains ``True`` sentinels (run cycle) or ``False``
        (shutdown signal).  We always check :attr:`_stop_event` before
        running so a rapid burst of graph events collapses to one cycle.
        """
        while not self._stop_event.is_set():
            try:
                trigger = self._cycle_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if not trigger or self._stop_event.is_set():
                break
            # Drain any queued-up additional triggers to prevent pile-up.
            while not self._cycle_queue.empty():
                try:
                    self._cycle_queue.get_nowait()
                except queue.Empty:
                    break
            self._run_cycle()

    def _run_cycle(self) -> None:
        """Detect patterns → generate suggestions → persist → publish."""
        log.info("[intelligence_engine] starting analysis cycle")
        try:
            patterns = detect_anti_patterns(
                self._graph,
                self._analyses,
                store=self._memory_store,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("[intelligence_engine] pattern detection failed: %s", exc)
            return

        if not patterns:
            log.info("[intelligence_engine] no patterns detected — cycle complete")
            return

        # Deduplicate: skip patterns already covered by a PENDING suggestion.
        pending = self._store.get_pending()
        pending_fingerprints = self._pending_fingerprints(pending)

        new_suggestions: list[Suggestion] = []
        for pattern in patterns:
            fp = pattern.fingerprint
            if fp in pending_fingerprints:
                log.debug(
                    "[intelligence_engine] skipping already-pending pattern: %s", fp
                )
                continue

            try:
                suggestion = suggest(pattern, self._store)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "[intelligence_engine] suggest() failed for %s: %s",
                    pattern.pattern_type, exc,
                )
                continue

            self._store.persist(suggestion)
            new_suggestions.append(suggestion)
            log.info(
                "[intelligence_engine] new suggestion persisted: id=%s pattern=%s",
                suggestion.id, pattern.pattern_type,
            )

        if new_suggestions:
            self._bus.publish(
                _OUTPUT_EVENT,
                {"suggestions": [s.to_dict() for s in new_suggestions]},
            )
            log.info(
                "[intelligence_engine] published %s with %d suggestion(s)",
                _OUTPUT_EVENT, len(new_suggestions),
            )
        else:
            log.info("[intelligence_engine] cycle complete — no new suggestions")

    @staticmethod
    def _pending_fingerprints(pending: list[Suggestion]) -> set[str]:
        """Build a set of fingerprint-like keys from pending suggestions.

        A fingerprint here is ``pattern_type::sorted_affected_files`` to match
        the :attr:`~intelligence.intelligence_types.Pattern.fingerprint` format.
        """
        result: set[str] = set()
        for s in pending:
            key = f"{s.pattern_type}::{':'.join(sorted(s.affected_files))}"
            result.add(key)
        return result
