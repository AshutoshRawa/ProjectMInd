"""
obsidian/vault_writer.py
========================
All Obsidian vault I/O for Module 8 goes through this single component.

Design rationale
----------------
- **Every** file write is serialised through :class:`WriteQueue`.  No other
  code in the obsidian package writes to disk directly — this eliminates
  race conditions when the watcher and docs engine fire simultaneously.
- The queue is a :class:`asyncio.PriorityQueue`-like structure backed by a
  ``heapq`` and a threading lock, so it can be used from both sync and async
  call-sites without an event loop requirement.
- Write tasks are retried up to **3 times** with a **200 ms backoff** on
  ``PermissionError`` (Obsidian locks files briefly during sync).
- Every completed write (success or failure) is appended to
  ``write_log.json`` in the vault root.

WriteTask priority
------------------
Lower integer = higher priority.  Callers should use the
:data:`Priority` constants for consistency::

    Priority.HIGH   = 0
    Priority.NORMAL = 10
    Priority.LOW    = 20
"""

from __future__ import annotations

import heapq
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from core.logger import get_logger
from core.utils import atomic_write_text, ensure_dir

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_RETRY_BACKOFF_S = 0.2        # 200 ms
_WRITE_LOG_FILENAME = "write_log.json"


class Priority:
    """Named priority levels for :class:`WriteTask`."""
    HIGH   = 0
    NORMAL = 10
    LOW    = 20


# ---------------------------------------------------------------------------
# WriteTask
# ---------------------------------------------------------------------------

Operation = Literal["write", "delete", "mkdir"]


@dataclass
class WriteTask:
    """
    A single vault file operation enqueued for serialised execution.

    Attributes
    ----------
    path:
        Absolute target path (file or directory).
    content:
        Text content to write.  Ignored for ``delete`` / ``mkdir``.
    operation:
        ``"write"`` | ``"delete"`` | ``"mkdir"``.
    priority:
        Lower = executed sooner.  Use :class:`Priority` constants.
    timestamp:
        Unix epoch float (set automatically on creation).
    """

    path: str
    content: str = ""
    operation: Operation = "write"
    priority: int = Priority.NORMAL
    timestamp: float = field(default_factory=time.time)

    # Heap comparison — (priority, timestamp, id) gives stable FIFO within
    # the same priority level.
    _seq: int = field(default_factory=lambda: next(_seq_counter), repr=False)

    def __lt__(self, other: "WriteTask") -> bool:
        return (self.priority, self.timestamp, self._seq) < (
            other.priority, other.timestamp, other._seq
        )

    def __le__(self, other: "WriteTask") -> bool:
        return (self.priority, self.timestamp, self._seq) <= (
            other.priority, other.timestamp, other._seq
        )


# Monotonic sequence counter for FIFO within the same priority.
_seq_counter = iter(range(10_000_000))


# ---------------------------------------------------------------------------
# WriteQueue
# ---------------------------------------------------------------------------

class WriteQueue:
    """
    Thread-safe priority queue for vault file operations.

    Usage
    -----
    .. code-block:: python

        wq = WriteQueue(vault_root=Path("/vault"))
        wq.start()
        wq.enqueue(WriteTask(path="/vault/Notes/x.md", content="# Hi"))
        wq.stop()

    Parameters
    ----------
    vault_root:
        The vault root directory.  The write-log is written here.
    """

    def __init__(self, vault_root: Path) -> None:
        self._vault_root = Path(vault_root)
        self._heap: list[WriteTask] = []
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._started = False
        self._log_path = self._vault_root / _WRITE_LOG_FILENAME

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the background worker thread."""
        if self._started:
            return
        self._started = True
        self._stop_event.clear()
        ensure_dir(self._vault_root)
        self._worker_thread = threading.Thread(
            target=self._worker,
            name="projectmind.module8.vault_writer",
            daemon=True,
        )
        self._worker_thread.start()
        log.info("[vault_writer] started — log=%s", self._log_path)

    def stop(self, *, drain: bool = True, timeout: float = 10.0) -> None:
        """
        Signal the worker to stop.

        Parameters
        ----------
        drain:
            If ``True`` (default), process all queued tasks before stopping.
        timeout:
            Maximum seconds to wait for the worker to finish.
        """
        if not self._started:
            return
        self._started = False

        if not drain:
            # Clear the queue so the worker exits immediately.
            with self._not_empty:
                self._heap.clear()

        self._stop_event.set()

        with self._not_empty:
            self._not_empty.notify_all()

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=timeout)
            self._worker_thread = None

        log.info("[vault_writer] stopped")

    # ------------------------------------------------------------------
    # Public enqueue
    # ------------------------------------------------------------------

    def enqueue(self, task: WriteTask) -> None:
        """Push *task* onto the priority queue."""
        with self._not_empty:
            heapq.heappush(self._heap, task)
            self._not_empty.notify()
        log.debug(
            "[vault_writer] enqueued op=%s priority=%d path=%s",
            task.operation, task.priority, task.path,
        )

    def qsize(self) -> int:
        """Return the current number of pending tasks."""
        with self._lock:
            return len(self._heap)

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        """Background thread: dequeue and execute one task at a time."""
        while True:
            with self._not_empty:
                while not self._heap:
                    if self._stop_event.is_set():
                        return
                    self._not_empty.wait(timeout=0.25)
                    if self._stop_event.is_set() and not self._heap:
                        return

                task = heapq.heappop(self._heap)

            self.execute_write(task)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_write(self, task: WriteTask) -> None:
        """
        Execute *task*, retrying on ``PermissionError``.

        Logs every attempt outcome to ``write_log.json``.
        """
        t_start = time.monotonic()
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                self._do_operation(task)
                elapsed_ms = (time.monotonic() - t_start) * 1000
                self._append_log(task, success=True, ms=elapsed_ms)
                log.debug(
                    "[vault_writer] ✓ op=%s path=%s attempt=%d (%.1f ms)",
                    task.operation, task.path, attempt, elapsed_ms,
                )
                return
            except PermissionError as exc:
                last_exc = exc
                log.warning(
                    "[vault_writer] PermissionError attempt %d/%d for %s: %s",
                    attempt, _MAX_RETRIES, task.path, exc,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_BACKOFF_S)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.error(
                    "[vault_writer] fatal error op=%s path=%s: %s",
                    task.operation, task.path, exc,
                )
                break  # Non-permission errors are not retried.

        elapsed_ms = (time.monotonic() - t_start) * 1000
        self._append_log(task, success=False, ms=elapsed_ms, error=str(last_exc))
        log.error(
            "[vault_writer] ✗ op=%s path=%s failed after %d attempt(s)",
            task.operation, task.path, _MAX_RETRIES,
        )

    def _do_operation(self, task: WriteTask) -> None:
        """Dispatch to the correct filesystem operation."""
        target = Path(task.path)
        if task.operation == "write":
            atomic_write_text(target, task.content)
        elif task.operation == "mkdir":
            ensure_dir(target)
        elif task.operation == "delete":
            if target.exists():
                target.unlink()
        else:
            log.warning("[vault_writer] unknown operation %r — skipping", task.operation)

    # ------------------------------------------------------------------
    # Write log
    # ------------------------------------------------------------------

    def _append_log(
        self,
        task: WriteTask,
        *,
        success: bool,
        ms: float,
        error: str | None = None,
    ) -> None:
        """Append one JSON line to ``write_log.json``."""
        entry: dict = {
            "ts": time.time(),
            "path": task.path,
            "operation": task.operation,
            "priority": task.priority,
            "success": success,
            "ms": round(ms, 2),
        }
        if error:
            entry["error"] = error

        try:
            ensure_dir(self._log_path.parent)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception as exc:  # noqa: BLE001
            log.warning("[vault_writer] could not write log entry: %s", exc)
