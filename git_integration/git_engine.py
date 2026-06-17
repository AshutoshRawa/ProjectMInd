"""
git/git_engine.py
=================
Module 9 — Git Intelligence Engine orchestrator.

Subscribes to ``"git.commit"`` events (published by GitMonitor),
summarises each commit via CommitSummarizer, stores it in GitMemory,
and re-publishes ``"git.commit_summarized"``.

This is the only component that wires M9's internal layers together.
"""

from __future__ import annotations

import queue
import threading
from typing import Any

from core.event_bus import EventBus
from core.logger import get_logger
from git_integration.commit_summarizer import summarize
from git_integration.git_memory import GitMemory
from git_integration.git_monitor import GitMonitor
from git_integration.git_types import CommitInfo

log = get_logger(__name__)

_IN  = "git.commit"
_OUT = "git.commit_summarized"


class GitEngine:
    """
    Orchestration service for Module 9.

    Parameters
    ----------
    bus:
        Shared :class:`~core.event_bus.EventBus`.
    ai:
        The :class:`~ai.ai_manager.AIManager` singleton (``get_ai()``).
    memory_store:
        The :class:`~memory.memory_store.MemoryStore` used by M7.
    repo_path:
        Path to the git repository to monitor.
    poll_interval:
        Seconds between HEAD polls (forwarded to GitMonitor).
    """

    name = "git"

    def __init__(
        self,
        *,
        bus: EventBus,
        ai: Any,
        memory_store: Any,
        repo_path: str,
        poll_interval: float = 30.0,
    ) -> None:
        self._bus = bus
        self._ai = ai
        self._git_memory = GitMemory(memory_store)
        self._monitor = GitMonitor(repo_path, bus, poll_interval=poll_interval)

        self._queue: queue.Queue[CommitInfo] = queue.Queue()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._bus_handler: Any | None = None
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop_event.clear()

        def _on_commit(payload: dict[str, Any]) -> None:
            commit = payload.get("commit")
            if isinstance(commit, CommitInfo):
                self._queue.put(commit)

        self._bus_handler = _on_commit
        self._bus.subscribe(_IN, _on_commit)

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="projectmind.module9.git_engine",
            daemon=True,
        )
        self._worker_thread.start()
        self._monitor.start()
        log.info("[git_engine] started")

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        self._monitor.stop()
        self._stop_event.set()

        if self._bus_handler:
            self._bus.unsubscribe(_IN, self._bus_handler)
            self._bus_handler = None

        if self._worker_thread:
            self._worker_thread.join(timeout=10.0)
            self._worker_thread = None

        log.info("[git_engine] stopped")

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                commit = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._process(commit)
            except Exception as exc:  # noqa: BLE001
                log.exception("[git_engine] error processing commit %s: %s", commit.short_hash, exc)

    def _process(self, commit: CommitInfo) -> None:
        summarize(commit, ai=self._ai)
        self._git_memory.store_commit(commit)
        self._bus.publish(_OUT, {"commit": commit})
        log.info("[git_engine] ✓ commit %s stored (impact=%.2f)", commit.short_hash, commit.impact_score)
