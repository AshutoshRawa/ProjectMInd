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

from core.config import AISettings, ConfigLoader, Settings
from core.event_bus import EventBus
from core.exceptions import (
    AIError,
    BootstrapError,
    ConfigError,
    ProjectMindError,
    PromptNotFoundError,
    RegistryError,
    ResponseParseError,
    VaultError,
    WatcherError,
)
from core.interfaces import AIClient, FileWatcher
from core.logger import get_logger, set_level
from core.registry import ServiceRegistry

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
    "ConfigLoader",
    "EventBus",
    "FileWatcher",
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
]
