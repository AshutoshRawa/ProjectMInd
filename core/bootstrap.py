"""
core/bootstrap.py
=================
Application startup orchestration for ProjectMind.

Responsibilities
----------------
1. Load configuration via :class:`core.config.ConfigLoader`.
2. Initialise the logging subsystem.
3. Create required directories (logs, vault sections).
4. Build core services and register them with a
   :class:`core.registry.ServiceRegistry`.
5. Hand back an :class:`Application` handle that the caller (typically
   :mod:`main`) drives until shutdown.
6. Wire SIGINT/SIGTERM handlers for graceful shutdown.

This module is the **only** place that knows the wiring graph; everywhere
else, code reads collaborators from the registry.
"""

from __future__ import annotations

import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core import logger as logger_module
from core.config import ConfigLoader, Settings
from core.exceptions import BootstrapError, ProjectMindError
from core.logger import get_logger
from core.registry import ServiceRegistry
from core.utils import ensure_dir
from obsidian.vault import VaultManager


# ---------------------------------------------------------------------------
# Application context
# ---------------------------------------------------------------------------

@dataclass
class Application:
    """
    Live application context returned by :func:`bootstrap`.

    Holds the long-lived collaborators that ``main`` (or future
    higher-level orchestrators) will drive.  Everything else in the
    codebase should reach these via ``app.registry.get(...)`` rather
    than holding a direct reference.
    """

    settings: Settings
    registry: ServiceRegistry
    project_root: Path
    _shutdown_hooks: list[Callable[[], None]]

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def on_shutdown(self, hook: Callable[[], None]) -> None:
        """Register a callable to be invoked (LIFO) during :meth:`shutdown`."""
        self._shutdown_hooks.append(hook)

    def shutdown(self) -> None:
        """
        Run shutdown hooks in reverse-registration order.

        Each hook is wrapped so a single failure cannot prevent the
        rest from running — graceful shutdown must be best-effort.
        """
        log = get_logger(__name__)
        log.info("Shutting down ProjectMind …")
        while self._shutdown_hooks:
            hook = self._shutdown_hooks.pop()
            try:
                hook()
            except Exception:  # noqa: BLE001 — defensive
                log.exception("Shutdown hook %r failed", hook)
        log.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def bootstrap(
    user_config_path: Path | None = None,
    *,
    install_signal_handlers: bool = True,
) -> Application:
    """
    Build a fully initialised :class:`Application`.

    Parameters
    ----------
    user_config_path:
        Override path to the user config YAML.  Mainly for tests.
    install_signal_handlers:
        If True (default), bind SIGINT/SIGTERM to a graceful shutdown.
        Tests pass False to avoid interfering with pytest's handlers.

    Returns
    -------
    Application
        Ready-to-use context with logger configured, vault initialised,
        and core services registered.
    """
    try:
        # 1. Load configuration ------------------------------------------------
        settings = ConfigLoader(user_config_path=user_config_path).load()

        # 2. Resolve the project root (paths.project_root may be relative) -----
        project_root = Path(settings.paths.project_root).resolve()

        # 3. Logging -----------------------------------------------------------
        logs_dir = ensure_dir(_resolve_path(project_root, settings.paths.logs_dir))
        logger_module.bootstrap(logs_dir, settings.logging)
        log = get_logger(__name__)
        log.info("Bootstrapping %s v%s", settings.app.name, settings.app.version)

        # 4. Vault -------------------------------------------------------------
        vault_dir = _resolve_path(project_root, settings.paths.vault_dir)
        vault = VaultManager(
            root=vault_dir,
            sections=settings.vault.sections,
            frontmatter=settings.vault.frontmatter,
        )
        vault.initialize()
        log.info("Vault initialised at %s (%d sections)",
                 vault_dir, len(settings.vault.sections))

        # 5. Service registry --------------------------------------------------
        registry = ServiceRegistry()
        registry.register(Settings, settings)
        registry.register(ServiceRegistry, registry)
        registry.register(VaultManager, vault)
        registry.register("project_root", project_root)
        registry.register("logs_dir", logs_dir)

        # 6. Build the Application handle -------------------------------------
        app = Application(
            settings=settings,
            registry=registry,
            project_root=project_root,
            _shutdown_hooks=[],
        )

        # 7. Signal handlers (optional) ---------------------------------------
        if install_signal_handlers:
            _install_signal_handlers(app)

        log.info("Bootstrap complete")
        return app

    except ProjectMindError:
        # Already a domain error (ConfigError, VaultError, …) — propagate
        # the specific subclass so callers can catch it precisely.
        raise
    except Exception as exc:  # noqa: BLE001
        # Wrap any unexpected/lower-level failure so callers can still
        # rely on a single ``ProjectMindError`` catch.
        raise BootstrapError(f"Failed to bootstrap ProjectMind: {exc}") from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_path(root: Path, candidate: str) -> Path:
    """Resolve *candidate* against *root* unless it is already absolute."""
    p = Path(candidate)
    return p if p.is_absolute() else (root / p).resolve()


def _install_signal_handlers(app: Application) -> None:
    """
    Bind SIGINT / SIGTERM to :meth:`Application.shutdown`.

    On unsupported platforms (e.g. inside a worker thread on Windows)
    ``signal.signal`` raises ``ValueError``; we silently fall back —
    the user can always Ctrl-C the foreground process.
    """
    log = get_logger(__name__)

    def _handle(signum: int, _frame) -> None:  # noqa: ANN001
        log.warning("Received signal %s — initiating graceful shutdown", signum)
        app.shutdown()
        sys.exit(0)

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _handle)
        except (ValueError, OSError):
            # Not on the main thread, or platform doesn't support it.
            log.debug("Could not install %s handler", sig_name)
