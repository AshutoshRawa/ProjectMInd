"""
core/registry.py
================
Service Registry — the dependency-safe wiring layer for ProjectMind.

Why a registry?
---------------
A monolithic ``import`` graph quickly turns into a tangle as the project
grows.  By having every long-lived service register itself with a single
:class:`ServiceRegistry` instance during bootstrap, downstream modules
can look up collaborators **by interface** without importing concrete
implementations directly.  This:

- breaks circular dependencies
- makes tests trivial (swap in a fake by registering it first)
- prepares the codebase for future plugin loading

Usage
-----
.. code-block:: python

    registry = ServiceRegistry()
    registry.register(Settings, settings)
    registry.register("vault", vault_manager)

    cfg   = registry.get(Settings)
    vault = registry.get("vault")

Keys may be either a ``type`` (preferred for interface-based lookup) or
a plain ``str`` (handy for ad-hoc named services).
"""

from __future__ import annotations

import threading
from typing import Any, Iterator, TypeVar, Union

from core.exceptions import RegistryError

T = TypeVar("T")
# NOTE: kept as ``typing.Union`` (not ``type | str``) so the alias is
# evaluable at runtime on Python < 3.10 too — handy for editors and
# CI runners that haven't upgraded yet.  The annotated *uses* of this
# alias still benefit from ``from __future__ import annotations``.
Key = Union[type, str]


class ServiceRegistry:
    """
    Thread-safe service container.

    The registry intentionally does **not** support auto-wiring or
    constructor injection.  Bootstrap code is the single place that
    builds and registers services; everywhere else only *reads* from
    the registry.  This keeps the dependency graph explicit and
    auditable.
    """

    def __init__(self) -> None:
        self._services: dict[Key, Any] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def register(self, key: Key, instance: Any, *, replace: bool = False) -> None:
        """
        Register *instance* under *key*.

        Parameters
        ----------
        key:
            Either an interface ``type`` (preferred) or a string label.
        instance:
            The service object to store.
        replace:
            If ``False`` (default) a duplicate registration raises
            :class:`RegistryError`.  Set to ``True`` for hot-swap
            scenarios such as tests.
        """
        with self._lock:
            if key in self._services and not replace:
                raise RegistryError(
                    f"Service for key {key!r} is already registered. "
                    "Pass replace=True to override."
                )
            self._services[key] = instance

    def unregister(self, key: Key) -> None:
        """Remove a previously registered service.  No-op if absent."""
        with self._lock:
            self._services.pop(key, None)

    def clear(self) -> None:
        """Drop every registered service.  Primarily useful in tests."""
        with self._lock:
            self._services.clear()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, key: Key) -> Any:
        """
        Retrieve a service.  Raises :class:`RegistryError` if missing,
        which is louder than ``KeyError`` and easier to grep for in logs.
        """
        with self._lock:
            try:
                return self._services[key]
            except KeyError as exc:
                raise RegistryError(
                    f"No service registered for key {key!r}. "
                    f"Available: {sorted(map(repr, self._services))}"
                ) from exc

    def has(self, key: Key) -> bool:
        """Return True iff *key* is currently registered."""
        with self._lock:
            return key in self._services

    def all(self) -> dict[Key, Any]:
        """Return a shallow copy of the registry contents."""
        with self._lock:
            return dict(self._services)

    # ------------------------------------------------------------------
    # Dunder convenience
    # ------------------------------------------------------------------

    def __contains__(self, key: Key) -> bool:
        return self.has(key)

    def __len__(self) -> int:
        with self._lock:
            return len(self._services)

    def __iter__(self) -> Iterator[Key]:
        with self._lock:
            return iter(list(self._services))

    def __repr__(self) -> str:
        with self._lock:
            keys = sorted(repr(k) for k in self._services)
        return f"ServiceRegistry({len(keys)} services: {keys})"
