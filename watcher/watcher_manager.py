"""
watcher/watcher_manager.py
============================
High-level Watcher Engine orchestration.

:class:`WatcherManager` is the concrete implementation of
:class:`~core.interfaces.FileWatcher`.  It:

- resolves configured watch directories under the project root
- attaches a recursive watchdog polling observer per directory
- filters and debounces events
- logs accepted changes (no AI / documentation in this module)
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from watchdog.observers.polling import PollingObserver

from core import FileWatcher, WatcherError, WatcherSettings, get_logger
from watcher.events import FileChangeEvent
from watcher.file_tracker import FileTracker
from watcher.filters import PathFilter
from watcher.watcher import ProjectMindEventHandler

log = get_logger(__name__)


class WatcherManager(FileWatcher):
    """
    Filesystem watcher service for ProjectMind.

    Parameters
    ----------
    project_root:
        Absolute path to the workspace root (parent of backend/, app/, …).
    settings:
        Watcher configuration from :class:`~core.config.Settings`.
    on_event:
        Optional callback for debounced events.  When omitted, events are
        logged at INFO level — sufficient for Module 2.
    """

    name = "watcher"

    def __init__(
        self,
        project_root: Path,
        settings: WatcherSettings,
        *,
        on_event: Callable[[FileChangeEvent], None] | None = None,
    ) -> None:
        self._project_root = project_root.resolve()
        self._settings = settings
        self._on_event = on_event or self._default_on_event

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
        try:
            self._on_event(event)
        except Exception:  # noqa: BLE001
            log.exception("Watcher event callback failed for %s", event)

    @staticmethod
    def _default_on_event(event: FileChangeEvent) -> None:
        """Log debounced, filtered events — Module 2 has no downstream pipeline."""
        log.info("[watcher] %s", event)
