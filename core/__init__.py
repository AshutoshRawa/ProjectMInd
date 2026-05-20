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

from core.config import ConfigLoader, Settings
from core.exceptions import (
    BootstrapError,
    ConfigError,
    ProjectMindError,
    RegistryError,
    VaultError,
)
from core.logger import get_logger, set_level
from core.registry import ServiceRegistry

__all__ = [
    "ConfigLoader",
    "Settings",
    "ServiceRegistry",
    "get_logger",
    "set_level",
    "ProjectMindError",
    "ConfigError",
    "RegistryError",
    "VaultError",
    "BootstrapError",
]
