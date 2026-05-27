"""
watcher/watcher.py
==================
Watchdog event handler — translates OS events into ProjectMind events.

This module is the only place that imports ``watchdog``.  Everything
else in ProjectMind depends on :mod:`watcher.events` and
:class:`~watcher.file_tracker.FileTracker`.
"""

from __future__ import annotations

from pathlib import Path

from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)

from core import get_logger
from watcher.events import ChangeKind
from watcher.file_tracker import FileTracker
from watcher.filters import PathFilter

log = get_logger(__name__)


class ProjectMindEventHandler(FileSystemEventHandler):
    """
    Watchdog callback that filters and debounces raw filesystem events.

    Parameters
    ----------
    path_filter:
        Decides which paths are eligible.
    tracker:
        Debounces accepted events before logging/forwarding.
    """

    def __init__(self, path_filter: PathFilter, tracker: FileTracker) -> None:
        super().__init__()
        self._filter = path_filter
        self._tracker = tracker

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            if isinstance(event, DirCreatedEvent):
                log.debug("Directory created (not tracked): %s", event.src_path)
            return
        if isinstance(event, FileCreatedEvent):
            self._handle_file(event.src_path, ChangeKind.CREATED)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if isinstance(event, FileModifiedEvent):
            self._handle_file(event.src_path, ChangeKind.MODIFIED)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if isinstance(event, FileDeletedEvent):
            self._handle_file(event.src_path, ChangeKind.DELETED)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not isinstance(event, FileMovedEvent) or event.is_directory:
            return
        dest = Path(event.dest_path)
        src = Path(event.src_path)
        if self._filter.is_allowed_file(src):
            self._tracker.record(src, ChangeKind.DELETED)
        if self._filter.is_allowed_file(dest):
            self._tracker.record(dest, ChangeKind.MOVED, src_path=src)

    def _handle_file(self, src_path: str, kind: ChangeKind) -> None:
        path = Path(src_path)
        if not self._filter.is_allowed_file(path):
            log.debug("Ignored %s event for %s", kind.value, path)
            return
        log.debug("Queued %s event for %s", kind.value, path)
        self._tracker.record(path, kind)
