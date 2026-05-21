"""
watcher/file_tracker.py
=======================
Debounce and deduplicate filesystem events.

Editors and build tools often emit rapid bursts of writes to the same
file.  :class:`FileTracker` collapses those into a single
:class:`~watcher.events.FileChangeEvent` per path after a quiet period
configured via ``watcher.debounce_seconds``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from watcher.events import ChangeKind, FileChangeEvent, make_event


class FileTracker:
    """
    Debounce incoming raw events before they are logged or forwarded.

    Parameters
    ----------
    debounce_seconds:
        How long to wait after the *last* event for a path before flushing.
    on_flush:
        Callback invoked once per path with the final merged event.
    """

    def __init__(
        self,
        debounce_seconds: float,
        on_flush: Callable[[FileChangeEvent], None],
    ) -> None:
        if debounce_seconds <= 0:
            raise ValueError("debounce_seconds must be greater than 0")
        self._debounce = debounce_seconds
        self._on_flush = on_flush
        self._lock = threading.RLock()
        # path → (kind, optional src_path for moves)
        self._pending: dict[Path, tuple[ChangeKind, Path | None]] = {}
        self._timer: threading.Timer | None = None

    def record(
        self,
        path: Path,
        kind: ChangeKind,
        *,
        src_path: Path | None = None,
    ) -> None:
        """
        Queue or update a pending event for *path* and (re)schedule flush.

        Later events for the same path replace earlier ones, keeping the
        *strongest* signal: ``deleted`` wins over ``modified`` wins over
        ``created`` so we do not log a modify after a delete in the same
        burst.
        """
        resolved = path.resolve()
        with self._lock:
            existing = self._pending.get(resolved)
            if existing is not None:
                kind = _merge_kind(existing[0], kind)
                # Preserve the original src_path from the first move in burst.
                src_path = existing[1] or src_path
            self._pending[resolved] = (kind, src_path)
            self._schedule_flush_locked()

    def flush_now(self) -> list[FileChangeEvent]:
        """
        Immediately emit all pending events.

        Primarily used in tests and during shutdown.
        """
        with self._lock:
            return self._flush_locked()

    def pending_count(self) -> int:
        """Number of paths waiting for debounce (mainly for tests)."""
        with self._lock:
            return len(self._pending)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _schedule_flush_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self._debounce, self._timer_callback)
        self._timer.daemon = True
        self._timer.start()

    def _timer_callback(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> list[FileChangeEvent]:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

        if not self._pending:
            return []

        batch = self._pending
        self._pending = {}
        emitted: list[FileChangeEvent] = []

        for path, (kind, src_path) in batch.items():
            event = make_event(path, kind, src_path=src_path)
            emitted.append(event)
            self._on_flush(event)

        return emitted


# Priority when two kinds arrive for the same path in one debounce window.
_KIND_PRIORITY = {
    ChangeKind.CREATED: 1,
    ChangeKind.MODIFIED: 2,
    ChangeKind.MOVED: 3,
    ChangeKind.DELETED: 4,
}


def _merge_kind(existing: ChangeKind, incoming: ChangeKind) -> ChangeKind:
    """Keep the higher-priority kind when collapsing duplicate paths."""
    if _KIND_PRIORITY[incoming] >= _KIND_PRIORITY[existing]:
        return incoming
    return existing
