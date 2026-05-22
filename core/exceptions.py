"""
core/exceptions.py
==================
Domain-specific exception hierarchy for ProjectMind.

Every error raised by ProjectMind code should derive from
:class:`ProjectMindError`.  This lets calling code catch *all* internal
failures with a single ``except`` clause while still allowing
fine-grained handling when desired.
"""

from __future__ import annotations


class ProjectMindError(Exception):
    """Root of the ProjectMind exception tree."""


class ConfigError(ProjectMindError):
    """Raised when configuration loading or validation fails."""


class RegistryError(ProjectMindError):
    """Raised by :class:`core.registry.ServiceRegistry` for bad lookups."""


class VaultError(ProjectMindError):
    """Raised by vault / markdown helpers on IO or schema problems."""


class BootstrapError(ProjectMindError):
    """Raised when application startup cannot complete."""


class WatcherError(ProjectMindError):
    """Raised when the filesystem watcher cannot start or operate."""


class AIError(ProjectMindError):
    """Raised when the AI communication layer cannot reach or use Ollama."""
