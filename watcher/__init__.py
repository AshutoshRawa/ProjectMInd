"""
watcher/
========
**Module 2 — Watcher Engine**

Recursively monitors configured project directories (``backend/``,
``frontend/``, ``src/``, ``app/``) for file create / modify / delete
events, applies ignore rules and extension filters, debounces bursts,
and logs stable :class:`~watcher.events.FileChangeEvent` records.

Future modules (analysis, documentation, AI) will subscribe to the same
event stream without importing watchdog directly.

Public API
----------
- :class:`~watcher.events.FileChangeEvent` — normalized event payload

Import :class:`watcher.watcher_manager.WatcherManager` directly when the
watchdog-backed service is needed.  Keeping this package initializer light
allows event types to be imported without requiring watchdog at import time.
"""

from watcher.events import ChangeKind, FileChangeEvent

__all__ = [
    "ChangeKind",
    "FileChangeEvent",
]
