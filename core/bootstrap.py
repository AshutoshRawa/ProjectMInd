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

from core import (
    EventBus,
    ConfigLoader,
    Settings,
    AIClient,
    Analyzer,
    DocumentationGenerator,
    FileWatcher,
    GraphBuilder,
    MemoryEngine,
    get_logger,
    ensure_dir,
    logger as logger_module,
)
from core.exceptions import BootstrapError, ProjectMindError
from core.registry import ServiceRegistry
from obsidian import VaultManager


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
        event_bus = EventBus()
        registry.register(EventBus, event_bus)

        # 5b. AI (Module 3) — always registered; started from main ------------
        from ai import init_ai

        ai_manager = init_ai(settings=settings.ai)
        registry.register(AIClient, ai_manager)
        ai_manager.register_event_handlers(event_bus)

        # 5c. Watcher (Module 2) — register when enabled, start from main ----
        if settings.watcher.enabled:
            from watcher import WatcherManager

            watcher = WatcherManager(
                project_root=project_root,
                settings=settings.watcher,
                bus=event_bus,  # publishes watcher.file_change directly
            )
            registry.register(FileWatcher, watcher)

        # 5d. Analysis (Module 4) — register when enabled, start from main
        if settings.analysis.enabled:
            from analysis import Module4AnalyzerEngine

            analysis_engine = Module4AnalyzerEngine(
                bus=event_bus,
                settings=settings.analysis,
            )
            registry.register(Analyzer, analysis_engine)

        # 5e. Docs (Module 5) — subscribe: analysis.file_analyzed
        if settings.docs.enabled:
            from docs import Module5DocEngine

            docs_engine = Module5DocEngine(bus=event_bus)
            registry.register(DocumentationGenerator, docs_engine)

        # 5f. Graph (Module 6) — subscribe: analysis.file_analyzed
        if settings.graph.enabled:
            from graph import Module6GraphEngine

            graph_engine = Module6GraphEngine(
                bus=event_bus,
                state_path=project_root / "graph_state.json",
            )
            registry.register(GraphBuilder, graph_engine)

        # 5g. Memory (Module 7) — subscribe: analysis.file_analyzed
        if settings.memory.enabled:
            from memory import MemoryUpdater
            from memory.memory_store import MemoryStore

            mem_store_path = _resolve_path(project_root, settings.memory.chroma_db_path)
            memory_store = MemoryStore(persist_directory=str(mem_store_path))
            memory_updater = MemoryUpdater(bus=event_bus, store=memory_store)
            registry.register(MemoryEngine, memory_updater)
            registry.register("memory_store", memory_store)

        # 5h. Obsidian (Module 8) — subscribe: docs.doc_updated + graph.graph_updated
        if settings.obsidian.enabled:
            from obsidian import ObsidianEngine

            mem_store = registry.get("memory_store") if settings.memory.enabled else None
            vault_dir = _resolve_path(project_root, settings.paths.vault_dir)
            obsidian_engine = ObsidianEngine(
                bus=event_bus,
                vault_root=vault_dir,
                memory_store=mem_store,
            )
            registry.register("obsidian", obsidian_engine)

        # 5i. Git (Module 9) — monitor commits, subscribe: git.commit
        if settings.git.enabled:
            from git_integration import GitEngine

            ai_client = registry.get(AIClient)
            mem_store = registry.get("memory_store") if settings.memory.enabled else None
            git_repo = _resolve_path(project_root, settings.git.repo_path)
            git_engine = GitEngine(
                bus=event_bus,
                ai=ai_client,
                memory_store=mem_store,
                repo_path=str(git_repo),
                poll_interval=settings.git.poll_interval_seconds,
            )
            registry.register("git", git_engine)

        # 5j. Intelligence (Module 10) — subscribe: graph.graph_updated
        if settings.intelligence.enabled:
            from intelligence import IntelligenceEngine, SuggestionStore

            graph_svc = registry.get(GraphBuilder) if settings.graph.enabled else None
            mem_store = registry.get("memory_store") if settings.memory.enabled else None
            store_path = _resolve_path(project_root, settings.intelligence.store_path)
            suggestion_store = SuggestionStore(store_path=store_path)
            intel_engine = IntelligenceEngine(
                bus=event_bus,
                graph=graph_svc.graph if graph_svc else __import__("networkx").DiGraph(),
                analyses=[],  # populated at runtime via analysis events
                store=suggestion_store,
                memory_store=mem_store,
                cycle_interval=settings.intelligence.cycle_interval_seconds,
            )
            registry.register("intelligence", intel_engine)

        # 6. Build the Application handle -------------------------------------
        app = Application(
            settings=settings,
            registry=registry,
            project_root=project_root,
            _shutdown_hooks=[],
        )

        # 7. Service shutdown hooks -------------------------------------------
        app.on_shutdown(ai_manager.stop)

        if settings.watcher.enabled:
            watcher_svc = registry.get(FileWatcher)
            app.on_shutdown(watcher_svc.stop)

        if settings.analysis.enabled:
            analysis_svc = registry.get(Analyzer)
            app.on_shutdown(analysis_svc.stop)

        if settings.docs.enabled:
            app.on_shutdown(registry.get(DocumentationGenerator).stop)

        if settings.graph.enabled:
            app.on_shutdown(registry.get(GraphBuilder).stop)

        if settings.memory.enabled:
            app.on_shutdown(registry.get(MemoryEngine).stop)

        if settings.obsidian.enabled:
            app.on_shutdown(registry.get("obsidian").stop)

        if settings.git.enabled:
            app.on_shutdown(registry.get("git").stop)

        if settings.intelligence.enabled:
            app.on_shutdown(registry.get("intelligence").stop)

        # 8. Signal handlers (optional) ---------------------------------------
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
