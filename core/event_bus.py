"""
Small in-process event bus for ProjectMind module communication.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from threading import RLock
from typing import Any

EventHandler = Callable[[dict[str, Any]], None]


class EventBus:
    """Synchronous pub/sub bus used to decouple ProjectMind modules."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Register *handler* for *event_name*."""
        with self._lock:
            self._handlers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """Remove *handler* from *event_name* if present."""
        with self._lock:
            if handler in self._handlers.get(event_name, []):
                self._handlers[event_name].remove(handler)

    def publish(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        """Publish *payload* to all subscribers for *event_name*."""
        with self._lock:
            handlers = list(self._handlers.get(event_name, []))
        event = payload or {}
        for handler in handlers:
            handler(event)
