"""
memory/memory_updater.py
========================
Module 7 orchestration layer — bridges the EventBus with the Memory Engine.

Responsibilities
----------------
1. Subscribe to ``analysis.file_analyzed`` (``ANALYSIS_DONE``) events
   emitted by Module 4.
2. Subscribe to ``watcher.file_change`` / ``analysis.file_analyzed`` delete
   events to handle ``FILE_DELETED``.
3. For **changed** files:
   a. Delete all existing chunks for that file path.
   b. Re-chunk via :mod:`memory.chunker`.
   c. Re-embed + upsert via :mod:`memory.memory_store`.
   d. Publish ``memory.updated`` on success.
4. For **deleted** files: call ``MemoryStore.delete_by_file`` and publish
   ``memory.deleted``.

Worker thread
-------------
All store operations run in a background daemon thread (same pattern as
Module 4's ``Module4AnalyzerEngine``) to avoid blocking the EventBus
dispatch path.

Event contracts
---------------
Inbound ``analysis.file_analyzed``::

    {
        "file_path": str,
        "analysis": dict | None,        # None means deleted / error
        "analysis_error": str | None,   # "deleted" | "file_missing" | …
        "change_kind": str,             # "modified" | "created" | "deleted"
    }

Outbound ``memory.updated``::

    {
        "file_path": str,
        "chunk_count": int,
        "chunk_ids": list[str],
    }

Outbound ``memory.deleted``::

    {
        "file_path": str,
    }
"""

from __future__ import annotations

import queue
import threading
from dataclasses import asdict
from typing import Any

from analysis.analysis_types import FileAnalysis
from core.event_bus import EventBus
from core.interfaces import MemoryEngine
from core.logger import get_logger
from memory.chunker import chunk_python_file
from memory.memory_store import MemoryStore

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Event name constants
# ---------------------------------------------------------------------------

_IN_ANALYSIS_DONE = "analysis.file_analyzed"
_OUT_MEMORY_UPDATED = "memory.updated"
_OUT_MEMORY_DELETED = "memory.deleted"


# ---------------------------------------------------------------------------
# Internal work-item
# ---------------------------------------------------------------------------

class _WorkItem:
    """Lightweight discriminated union for the worker queue."""

    __slots__ = ("kind", "file_path", "analysis")

    def __init__(
        self,
        kind: str,
        file_path: str,
        analysis: FileAnalysis | None = None,
    ) -> None:
        self.kind = kind            # "update" | "delete"
        self.file_path = file_path
        self.analysis = analysis


# ---------------------------------------------------------------------------
# MemoryUpdater
# ---------------------------------------------------------------------------

class MemoryUpdater(MemoryEngine):
    """
    Module 7 — Memory Updater Service.

    Subscribes to Module 4 events and keeps the vector store in sync.

    Parameters
    ----------
    bus:
        Shared :class:`~core.event_bus.EventBus` instance.
    store:
        A :class:`~memory.memory_store.MemoryStore` instance (created by
        the caller so the ChromaDB path can be injected/mocked in tests).
    """

    name = "memory"

    def __init__(self, *, bus: EventBus, store: MemoryStore) -> None:
        self._bus = bus
        self._store = store
        self._queue: queue.Queue[_WorkItem] = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._bus_handler: Any | None = None
        self._started = False

    # ------------------------------------------------------------------
    # Service lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Subscribe to bus events and start the background worker."""
        if self._started:
            return
        self._started = True

        self._stop_event.clear()
        self._queue = queue.Queue()

        self._bus_handler = self._on_analysis_event
        self._bus.subscribe(_IN_ANALYSIS_DONE, self._bus_handler)

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="projectmind.module7.memory",
            daemon=True,
        )
        self._worker_thread.start()

        log.info(
            "[memory_updater] started — subscribed to '%s'",
            _IN_ANALYSIS_DONE,
        )

    def stop(self) -> None:
        """Unsubscribe and stop the worker thread gracefully."""
        if not self._started:
            return
        self._started = False

        self._stop_event.set()

        if self._bus_handler is not None:
            self._bus.unsubscribe(_IN_ANALYSIS_DONE, self._bus_handler)
            self._bus_handler = None

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=10.0)
            self._worker_thread = None

        log.info("[memory_updater] stopped")

    # ------------------------------------------------------------------
    # Public helpers (also callable directly for testing)
    # ------------------------------------------------------------------

    def on_file_changed(self, analysis: FileAnalysis) -> None:
        """
        Handle a changed/created file synchronously (no queue).

        1. Delete all existing chunks for this file_path.
        2. Re-chunk using :mod:`memory.chunker`.
        3. Re-embed and upsert all new chunks.
        4. Publish ``memory.updated``.
        """
        fp = analysis.path
        log.debug("[memory_updater] on_file_changed: %s", fp)

        # Step 1: wipe stale chunks.
        self._store.delete_by_file(fp)

        # Step 2: re-chunk.
        chunks = chunk_python_file(analysis)

        if not chunks:
            log.warning("[memory_updater] no chunks produced for %s", fp)
            return

        # Step 3: embed + upsert.
        self._store.upsert(chunks)

        # Step 4: publish success.
        self._bus.publish(
            _OUT_MEMORY_UPDATED,
            {
                "file_path": fp,
                "chunk_count": len(chunks),
                "chunk_ids": [c.id for c in chunks],
            },
        )
        log.info(
            "[memory_updater] updated %s — %d chunks stored",
            fp,
            len(chunks),
        )

    def on_file_deleted(self, path: str) -> None:
        """
        Handle a deleted file synchronously.

        Removes all stored chunks for *path* and publishes ``memory.deleted``.
        """
        log.debug("[memory_updater] on_file_deleted: %s", path)
        self._store.delete_by_file(path)
        self._bus.publish(_OUT_MEMORY_DELETED, {"file_path": path})
        log.info("[memory_updater] deleted memory for %s", path)

    # ------------------------------------------------------------------
    # EventBus handler (runs in the bus dispatch thread)
    # ------------------------------------------------------------------

    def _on_analysis_event(self, payload: dict[str, Any]) -> None:
        """
        Receive an ``analysis.file_analyzed`` payload and enqueue work.

        This runs synchronously in the EventBus dispatch thread so we
        must return quickly.  Heavy work goes to the queue.
        """
        file_path: str | None = payload.get("file_path")
        if not file_path:
            return

        analysis_dict: dict | None = payload.get("analysis")
        analysis_error: str | None = payload.get("analysis_error")

        if analysis_error == "deleted" or analysis_dict is None:
            # Treat as deletion.
            self._queue.put(_WorkItem(kind="delete", file_path=file_path))
            return

        try:
            analysis = FileAnalysis.from_dict(analysis_dict)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "[memory_updater] could not parse FileAnalysis for %s: %s",
                file_path,
                exc,
            )
            return

        self._queue.put(
            _WorkItem(kind="update", file_path=file_path, analysis=analysis)
        )

    # ------------------------------------------------------------------
    # Worker loop (background thread)
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                if item.kind == "update" and item.analysis is not None:
                    self.on_file_changed(item.analysis)
                elif item.kind == "delete":
                    self.on_file_deleted(item.file_path)
            except Exception as exc:  # noqa: BLE001
                log.exception(
                    "[memory_updater] error processing %s for %s: %s",
                    item.kind,
                    item.file_path,
                    exc,
                )
