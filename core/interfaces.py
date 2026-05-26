"""
core/interfaces.py
==================
Foundational abstract interfaces used across ProjectMind.

Future modules (watcher, ai, analysis, memory, graph, …) will provide
concrete implementations of these contracts.  Keeping the abstractions
here — rather than buried inside their owning packages — means any
module can depend on an interface without pulling in another module's
implementation.

Design rules
------------
- Interfaces are **deliberately small**.  We add methods only when a
  real caller needs them.
- We use :class:`abc.ABC` for behavioural contracts and
  :class:`typing.Protocol` for structural typing where duck-typing is
  preferable (e.g. anything resembling "a thing with a name").
- No interface here may import from a sibling module under
  ``ai/``, ``watcher/`` etc. — that would invert the dependency.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class Service(ABC):
    """
    Base class for every long-lived ProjectMind service.

    A *service* is anything the bootstrap layer needs to start at
    application startup and gracefully tear down at shutdown — for
    example the file watcher, the AI client, or the memory engine.

    Subclasses MUST be safe to instantiate without side effects; all
    real work belongs in :meth:`start`.
    """

    #: Short, human-readable identifier used in logs and registry keys.
    name: str = "service"

    @abstractmethod
    def start(self) -> None:
        """Acquire resources and begin operating.  Must be idempotent."""

    @abstractmethod
    def stop(self) -> None:
        """Release resources.  Must be idempotent and not raise."""

    # Default no-op health probe so callers can rely on its presence.
    def healthy(self) -> bool:
        """Return True if the service is operational."""
        return True


# ---------------------------------------------------------------------------
# Storage abstractions (used by Module 1's vault helpers; reused later)
# ---------------------------------------------------------------------------

@runtime_checkable
class NoteStore(Protocol):
    """
    Anything capable of persisting and retrieving named markdown notes.

    The vault implementation in :mod:`obsidian.vault` is the canonical
    in-tree implementation; future modules (e.g. a remote sync backend)
    can satisfy this protocol without inheriting from a base class.
    """

    def write_note(
        self,
        section: str,
        name: str,
        body: str,
        frontmatter_extras: dict[str, Any] | None = None,
    ) -> Path: ...
    def read_note(self, section: str, name: str) -> tuple[dict[str, Any], str]: ...
    def note_exists(self, section: str, name: str) -> bool: ...
    def list_notes(self, section: str) -> list[str]: ...


# ---------------------------------------------------------------------------
# Future-module placeholders
# ---------------------------------------------------------------------------
# These are intentionally tiny — they exist so other code can type-hint
# against them today even though no implementation ships in Module 1.

class FileWatcher(Service):
    """Implemented by :class:`watcher.watcher_manager.WatcherManager`."""

    name = "watcher"


class AIClient(Service):
    """Implemented by :class:`ai.ai_manager.AIManager`."""

    name = "ai"

    @abstractmethod
    def complete(self, prompt_name: str, variables: dict[str, Any], stream: bool = False) -> str:
        """Render a registered prompt template and run it through the model."""

    @abstractmethod
    def complete_raw(self, prompt_text: str) -> str:
        """Send raw prompt text to the model without template lookup."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the Ollama server is reachable."""


class Analyzer(Service):
    """Will be implemented by ``analysis/`` in Module 4."""

    name = "analysis"


class MemoryEngine(Service):
    """Will be implemented by ``memory/`` in Module 5."""

    name = "memory"


class GraphBuilder(Service):
    """Will be implemented by ``graph/`` in Module 6."""

    name = "graph"
