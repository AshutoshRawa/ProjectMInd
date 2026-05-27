"""
watcher/events.py
=================
Normalized filesystem event types for the Watcher Engine.

Watchdog emits low-level, platform-specific events.  This module
translates them into a small, stable vocabulary that future modules
(analysis, documentation, memory) can consume without importing watchdog.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from core import now_iso


class ChangeKind(str, Enum):
    """
    High-level change categories ProjectMind cares about.

    Using ``str`` as a mixin so values serialize cleanly to logs and
    future JSON payloads without extra conversion.
    """

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


@dataclass(frozen=True)
class FileChangeEvent:
    """
    A single, debounced filesystem change ready for downstream processing.

    Attributes
    ----------
    path:
        Absolute path to the affected file.
    kind:
        What happened to the file.
    timestamp:
        ISO-8601 UTC time when ProjectMind *accepted* the event (after
        filtering/debounce), not the raw OS timestamp.
    src_path:
        For move/rename events, the original path.  ``None`` otherwise.
    """

    path: Path
    kind: ChangeKind
    timestamp: str
    src_path: Path | None = None

    def __str__(self) -> str:
        if self.kind == ChangeKind.MOVED and self.src_path is not None:
            return f"{self.kind.value}: {self.src_path} -> {self.path}"
        return f"{self.kind.value}: {self.path}"


def make_event(
    path: Path,
    kind: ChangeKind,
    *,
    src_path: Path | None = None,
) -> FileChangeEvent:
    """Factory helper — keeps timestamp generation in one place."""
    return FileChangeEvent(
        path=path.resolve(),
        kind=kind,
        timestamp=now_iso(),
        src_path=src_path.resolve() if src_path else None,
    )
