"""
docs/doc_engine.py
==================
Module 5 service: subscribes to ``analysis.file_analyzed`` events and
publishes ``docs.doc_updated`` with the generated markdown.

This module **produces markdown strings only** — it never writes to the
vault.  Vault persistence is Module 8's responsibility.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import asdict
from typing import Any

from analysis.analysis_types import FileAnalysis
from core import Analyzer, EventBus, get_logger
from docs.changelog import ChangelogEntry, diff_analyses
from docs.doc_generator import generate
from docs.frontmatter import build_frontmatter

log = get_logger(__name__)


class Module5DocEngine(Analyzer):
    """Long-lived service that converts analysis results into documentation.

    Lifecycle
    ---------
    1. ``start()`` subscribes to ``analysis.file_analyzed`` on the EventBus.
    2. For each incoming analysis payload the engine:
       a. Diffs against the previous analysis (if any) to build a changelog.
       b. Generates a full markdown document.
       c. Publishes a ``docs.doc_updated`` event.
    3. ``stop()`` tears down the worker thread and unsubscribes.
    """

    name = "docs"

    def __init__(
        self,
        *,
        bus: EventBus,
        input_event: str = "analysis.file_analyzed",
        output_event: str = "docs.doc_updated",
    ) -> None:
        self._bus = bus
        self._input_event = input_event
        self._output_event = output_event

        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._bus_handler: Any | None = None
        self._started = False

        # Cache of the last FileAnalysis per file path for changelog diffing.
        self._previous: dict[str, FileAnalysis] = {}

    # ------------------------------------------------------------------
    # Service lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True

        self._stop_event.clear()
        self._queue = queue.Queue()

        def _on_analysis(payload: dict[str, Any]) -> None:
            self._queue.put(payload)

        self._bus_handler = _on_analysis
        self._bus.subscribe(self._input_event, _on_analysis)

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="projectmind.module5.docs",
            daemon=True,
        )
        self._worker_thread.start()

        log.info("[docs] subscribed to %s and started worker", self._input_event)

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

        log.info("[docs] stopped")

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
                log.exception("[docs] failed to generate doc: %s", exc)

    def _process(self, payload: dict[str, Any]) -> None:
        # Skip payloads for deleted or errored files.
        analysis_raw = payload.get("analysis")
        if analysis_raw is None:
            return

        file_path = payload.get("file_path", "")

        # Reconstruct FileAnalysis from the dict payload.
        if isinstance(analysis_raw, dict):
            analysis = FileAnalysis.from_dict(analysis_raw)
        elif isinstance(analysis_raw, FileAnalysis):
            analysis = analysis_raw
        else:
            return

        # Build changelog by diffing against the cached previous analysis.
        changelog_entries: list[ChangelogEntry] = []
        previous = self._previous.get(file_path)
        if previous is not None:
            changelog_entries = diff_analyses(previous, analysis)

        # Cache for next diff.
        self._previous[file_path] = analysis

        # Generate the markdown document.
        markdown_content = generate(analysis, changelog_entries=changelog_entries)
        frontmatter_str = build_frontmatter(analysis)

        self._bus.publish(
            self._output_event,
            {
                "path": file_path,
                "markdown_content": markdown_content,
                "frontmatter": frontmatter_str,
            },
        )
