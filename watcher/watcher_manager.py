"""
watcher/watcher_manager.py
============================
High-level Watcher Engine orchestration.

:class:`WatcherManager` is the concrete implementation of
:class:`~core.interfaces.FileWatcher`.  It:

- resolves configured watch directories under the project root
- attaches a recursive watchdog polling observer per directory
- filters and debounces events
- publishes :data:`WATCHER_EVENT` on the :class:`~core.EventBus` when one is
  injected (preferred), *or* invokes an ``on_event`` callback (legacy/testing)
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.observers.polling import PollingObserver

from core import FileWatcher, WatcherError, WatcherSettings, get_logger
from watcher.events import FileChangeEvent
from watcher.file_tracker import FileTracker
from watcher.filters import PathFilter
from watcher.watcher import ProjectMindEventHandler

if TYPE_CHECKING:
    from core import EventBus

log = get_logger(__name__)

#: EventBus topic published by :class:`WatcherManager`.
WATCHER_EVENT = "watcher.file_change"


class WatcherManager(FileWatcher):
    """
    Filesystem watcher service for ProjectMind.

    Parameters
    ----------
    project_root:
        Absolute path to the workspace root (parent of backend/, app/, …).
    settings:
        Watcher configuration from :class:`~core.config.Settings`.
    bus:
        :class:`~core.EventBus` instance.  When provided, each debounced
        :class:`FileChangeEvent` is published as ``watcher.file_change``
        directly from this class — no bridging adaptor is needed in
        ``bootstrap.py``.
    on_event:
        Optional *additional* callback invoked **after** the bus publish.
        Kept for backward-compatibility with tests and standalone use.
        When neither *bus* nor *on_event* is supplied, events are logged
        at INFO level only.
    """

    name = "watcher"

    def __init__(
        self,
        project_root: Path,
        settings: WatcherSettings,
        *,
        bus: "EventBus | None" = None,
        on_event: Callable[[FileChangeEvent], None] | None = None,
    ) -> None:
        self._project_root = project_root.resolve()
        self._settings = settings
        self._bus = bus
        self._on_event = on_event  # may be None — handled in _dispatch_event

        self._path_filter = PathFilter(settings, self._project_root)
        self._tracker = FileTracker(
            debounce_seconds=settings.debounce_seconds,
            on_flush=self._dispatch_event,
        )
        self._handler = ProjectMindEventHandler(self._path_filter, self._tracker)
        self._observer: PollingObserver | None = None
        self._started = False
        self._active_watch_count = 0
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # FileWatcher / Service lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start observing all configured watch directories."""
        if self._started:
            return

        self._stop_event.clear()
        watch_paths = self._resolve_watch_paths()
        if not watch_paths:
            log.warning(
                "Watcher enabled but no watch directories exist under %s "
                "(looked for: %s)",
                self._project_root,
                ", ".join(self._settings.watch_dirs),
            )
            self._started = True
            self._stop_event.set()
            return

        try:
            self._observer = PollingObserver()
            for watch_path in watch_paths:
                self._observer.schedule(
                    self._handler,
                    str(watch_path),
                    recursive=True,
                )
                log.info("Watching %s (recursive)", watch_path)

            self._active_watch_count = len(watch_paths)
            self._observer.start()
            self._started = True
            log.info(
                "Watcher engine started — %d director%s, debounce %.1fs",
                len(watch_paths),
                "y" if len(watch_paths) == 1 else "ies",
                self._settings.debounce_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            raise WatcherError(f"Failed to start filesystem watcher: {exc}") from exc

    def stop(self) -> None:
        """Stop the observer and flush any pending debounced events."""
        if not self._started:
            return

        self._stop_event.set()

        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None

        # Emit anything still in the debounce buffer.
        self._tracker.flush_now()
        self._started = False
        self._stop_event.set()
        log.info("Watcher engine stopped")

    def healthy(self) -> bool:
        """True while at least one directory is being observed."""
        if (
            not self._started
            or self._observer is None
            or self._active_watch_count == 0
        ):
            return False
        return self._observer.is_alive()

    def wait_until_stopped(self) -> None:
        """
        Block until :meth:`stop` is called.

        Used by :mod:`main` to keep the process alive while watching.
        """
        self._stop_event.wait()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_watch_paths(self) -> list[Path]:
        """Return absolute paths of existing watch directories."""
        resolved: list[Path] = []
        for name in self._settings.watch_dirs:
            candidate = (self._project_root / name).resolve()
            if candidate.is_dir():
                resolved.append(candidate)
            else:
                log.debug("Watch directory not found, skipping: %s", candidate)
        return resolved

    def _dispatch_event(self, event: FileChangeEvent) -> None:
        """Publish the event on the EventBus and/or call the legacy callback.

        Priority order:
        1. If a :class:`~core.EventBus` was injected, publish on it.
        2. If an ``on_event`` callback was provided, call it.
        3. If neither, fall back to a plain INFO log.
        """
        published = False
        if self._bus is not None:
            try:
                self._bus.publish(WATCHER_EVENT, {"event": event})
                published = True
            except Exception:  # noqa: BLE001
                log.exception("EventBus publish failed for %s", event)

        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:  # noqa: BLE001
                log.exception("Watcher event callback failed for %s", event)
        elif not published:
            # Neither bus nor callback — log so events are never silently dropped.
            self._default_on_event(event)

    @staticmethod
    def _default_on_event(event: FileChangeEvent) -> None:
        """Log debounced, filtered events — Module 2 has no downstream pipeline."""
        log.info("[watcher] %s", event)
