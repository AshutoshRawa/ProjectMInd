"""
core/__init__.py
================
Public surface of the ProjectMind core package.

Only symbols that other packages legitimately need to import from
``core`` are listed here.  Keeping this file lean prevents accidental
circular imports as the project grows.

Note: :func:`core.bootstrap.bootstrap` is *not* re-exported because
importing it eagerly would pull in the vault layer at package-load
time.  Import it explicitly::

    from core.bootstrap import bootstrap
"""

from __future__ import annotations

from core.config import (
    AISettings,
    AnalysisSettings,
    ConfigLoader,
    GraphSettings,
    MemorySettings,
    Settings,
    VaultFrontmatterSettings,
    VaultSettings,
    WatcherSettings,
)
from core.event_bus import EventBus
from core.exceptions import (
    AIError,
    BootstrapError,
    ConfigError,
    ProjectMindError,
    VaultError,
    PromptNotFoundError,
    RegistryError,
    ResponseParseError,
    WatcherError,
)
from core.interfaces import AIClient, Analyzer, FileWatcher, GraphBuilder, MemoryEngine
from core.logger import get_logger, set_level
from core.registry import ServiceRegistry
from core.utils import atomic_write_text, ensure_dir, now_iso, slugify

_config: Settings | None = None


def get_config() -> Settings:
    """Load and cache the ProjectMind configuration."""
    global _config
    if _config is None:
        _config = ConfigLoader().load()
    return _config

__all__ = [
    "AIClient",
    "AISettings",
    "Analyzer",
    "AnalysisSettings",
    "ConfigLoader",
    "GraphBuilder",
    "GraphSettings",
    "EventBus",
    "FileWatcher",
    "MemoryEngine",
    "MemorySettings",
    "VaultFrontmatterSettings",
    "VaultSettings",
    "Settings",
    "ServiceRegistry",
    "get_config",
    "get_logger",
    "set_level",
    "AIError",
    "ProjectMindError",
    "ConfigError",
    "PromptNotFoundError",
    "RegistryError",
    "ResponseParseError",
    "VaultError",
    "WatcherError",
    "BootstrapError",
    "atomic_write_text",
    "ensure_dir",
    "now_iso",
    "slugify",
]
