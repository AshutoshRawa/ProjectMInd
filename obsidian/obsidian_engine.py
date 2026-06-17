"""
obsidian/obsidian_engine.py
===========================
Module 8 — Obsidian Integration Engine.

Orchestration layer that bridges the EventBus with the vault writer.

Responsibilities
----------------
1. Subscribe to ``docs.doc_updated``  (published by Module 5).
2. Subscribe to ``graph.graph_updated`` (published by Module 6).
3. On ``docs.doc_updated``:
   - Look up graph links for the file from the cached graph payload.
   - Run a semantic search (Module 7) to find related chunks.
   - Build the enriched note via :mod:`obsidian.note_builder`.
   - Enqueue a ``WriteTask`` on the :class:`~obsidian.vault_writer.WriteQueue`.
   - Update the :class:`~obsidian.vault_index.VaultIndex`.
4. On ``graph.graph_updated``:
   - Cache the graph payload (edges for a given node) for use in step 3.
5. **Never** generate documentation or graph data — consume only.

Vault path
----------
Resolved from ``config.paths.vault_dir`` relative to ``config.paths.project_root``.
Never hardcoded.

Event contracts
---------------
Inbound ``docs.doc_updated``::

    {
        "path": str,               # source file path
        "markdown_content": str,   # raw markdown from Module 5
        "frontmatter": str,        # YAML frontmatter string
    }

Inbound ``graph.graph_updated``::

    {
        "updated_node": str,
        "edges_added": list[str],
        "edges_removed": list[str],
        "stats": dict,
    }

Outbound ``obsidian.note_written``::

    {
        "source_path": str,
        "note_path": str,
        "chunk_count": int,
    }
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any

from core.event_bus import EventBus
from core.interfaces import Service
from core.logger import get_logger
from core.utils import ensure_dir, slugify
from obsidian.note_builder import build_note
from obsidian.vault_index import VaultIndex
from obsidian.vault_writer import Priority, WriteQueue, WriteTask

log = get_logger(__name__)

_IN_DOC_UPDATED   = "docs.doc_updated"
_IN_GRAPH_UPDATED = "graph.graph_updated"
_OUT_NOTE_WRITTEN = "obsidian.note_written"


class ObsidianEngine(Service):
    """
    Module 8 — Obsidian Integration Engine.

    Parameters
    ----------
    bus:
        Shared :class:`~core.event_bus.EventBus`.
    vault_root:
        Absolute path to the Obsidian vault directory.
    memory_store:
        Optional :class:`~memory.memory_store.MemoryStore` for semantic
        search.  If ``None``, semantic neighbors are skipped.
    top_k_neighbors:
        Maximum semantic neighbors to append to each note.
    """

    name = "obsidian"

    def __init__(
        self,
        *,
        bus: EventBus,
        vault_root: str | Path,
        memory_store: Any | None = None,
        top_k_neighbors: int = 3,
    ) -> None:
        self._bus = bus
        self._vault_root = Path(vault_root).resolve()
        self._memory_store = memory_store
        self._top_k = top_k_neighbors

        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started = False

        # Bus subscription handles (kept for unsubscribe on stop).
        self._doc_handler: Any | None = None
        self._graph_handler: Any | None = None

        # Cache: source_file_path → list of connected file paths (graph edges).
        self._graph_edges: dict[str, list[str]] = {}

        # Initialise subsystems (lazy — no I/O yet).
        self._write_queue = WriteQueue(vault_root=self._vault_root)
        self._index = VaultIndex(vault_root=self._vault_root)

    # ------------------------------------------------------------------
    # Service lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the engine: launch writer, scan index, subscribe to events."""
        if self._started:
            return
        self._started = True

        ensure_dir(self._vault_root)
        self._write_queue.start()
        self._index.rescan()
        self._stop_event.clear()

        # Subscribe to inbound events.
        def _on_doc(payload: dict[str, Any]) -> None:
            self._queue.put({"type": "doc", "payload": payload})

        def _on_graph(payload: dict[str, Any]) -> None:
            self._queue.put({"type": "graph", "payload": payload})

        self._doc_handler = _on_doc
        self._graph_handler = _on_graph
        self._bus.subscribe(_IN_DOC_UPDATED, _on_doc)
        self._bus.subscribe(_IN_GRAPH_UPDATED, _on_graph)

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="projectmind.module8.obsidian",
            daemon=True,
        )
        self._worker_thread.start()
        log.info(
            "[obsidian] started — vault=%s, %d existing notes",
            self._vault_root,
            self._index.note_count(),
        )

    def stop(self) -> None:
        """Gracefully stop the engine."""
        if not self._started:
            return
        self._started = False

        self._stop_event.set()

        if self._doc_handler is not None:
            self._bus.unsubscribe(_IN_DOC_UPDATED, self._doc_handler)
            self._doc_handler = None
        if self._graph_handler is not None:
            self._bus.unsubscribe(_IN_GRAPH_UPDATED, self._graph_handler)
            self._graph_handler = None

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=10.0)
            self._worker_thread = None

        self._write_queue.stop(drain=True)
        log.info("[obsidian] stopped")

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                if item["type"] == "doc":
                    self._handle_doc(item["payload"])
                elif item["type"] == "graph":
                    self._handle_graph(item["payload"])
            except Exception as exc:  # noqa: BLE001
                log.exception("[obsidian] error handling %s event: %s", item["type"], exc)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_graph(self, payload: dict[str, Any]) -> None:
        """Cache graph edges for a node so doc handler can use them."""
        node: str = payload.get("updated_node", "")
        if not node:
            return
        edges_added: list[str] = payload.get("edges_added", [])
        edges_removed: list[str] = payload.get("edges_removed", [])

        existing = self._graph_edges.get(node, [])
        # Merge new additions, then strip any removed edges.
        merged = list(dict.fromkeys(existing + edges_added))  # preserve order, dedup
        if edges_removed:
            removed_set = set(edges_removed)
            merged = [e for e in merged if e not in removed_set]
        self._graph_edges[node] = merged
        log.debug("[obsidian] graph cache updated for %s: %d edges", node, len(merged))

    def _handle_doc(self, payload: dict[str, Any]) -> None:
        """Build enriched note and enqueue a write."""
        source_path: str = payload.get("path", "")
        markdown: str = payload.get("markdown_content", "")
        frontmatter_str: str = payload.get("frontmatter", "")

        if not source_path or not markdown:
            log.warning("[obsidian] doc_updated payload missing path or content")
            return

        # Combine frontmatter + body as produced by Module 5.
        doc_markdown = (frontmatter_str + "\n" + markdown).strip() + "\n" if frontmatter_str else markdown

        # Graph links for this file.
        graph_links = self._graph_edges.get(source_path, [])

        # Semantic neighbors from Module 7.
        related_chunks: list[Any] = []
        if self._memory_store is not None:
            try:
                from memory.semantic_search import search_by_file  # noqa: PLC0415
                related_chunks = search_by_file(
                    source_path,
                    store=self._memory_store,
                    top_k=self._top_k,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("[obsidian] semantic search failed for %s: %s", source_path, exc)

        # Build enriched note.
        note_content = build_note(
            doc_markdown,
            graph_links,
            related_chunks,
            vault_root=str(self._vault_root),
        )

        # Determine target note path inside vault.
        stem = slugify(Path(source_path).stem)
        note_path = self._vault_root / "Generated" / f"{stem}.md"
        ensure_dir(note_path.parent)

        # Enqueue the write task.
        task = WriteTask(
            path=str(note_path),
            content=note_content,
            operation="write",
            priority=Priority.NORMAL,
        )
        self._write_queue.enqueue(task)

        # Update index.
        self._index.update(
            note_path,
            "write",
            source_file_path=source_path,
        )

        # Publish outbound event.
        self._bus.publish(
            _OUT_NOTE_WRITTEN,
            {
                "source_path": source_path,
                "note_path": str(note_path),
                "chunk_count": len(related_chunks),
            },
        )
        log.info("[obsidian] note queued: %s → %s", source_path, note_path)
