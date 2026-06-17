"""
main.py
=======
ProjectMind entry point.

Run with::

    python main.py

Module 1 bootstraps config, logging, vault, and the service registry.
Module 2 adds an optional filesystem watcher (``watcher.enabled: true``).
Module 3 connects to Ollama/Qwen at ``ai.ollama_host`` (requires a running
Ollama server and a pulled Qwen model).
Modules 4–10 are enabled via their respective ``<module>.enabled: true`` flags.
"""

from __future__ import annotations

import sys

from core.bootstrap import bootstrap
from core import (
    AIClient, Analyzer, DocumentationGenerator,
    FileWatcher, GraphBuilder, MemoryEngine,
    get_logger,
)
from core import ProjectMindError


def main() -> int:
    """Run ProjectMind.  Returns a process exit code."""
    try:
        app = bootstrap()
    except ProjectMindError as exc:
        # Logging may not be configured yet, so go to stderr directly.
        print(f"[FATAL] {exc}", file=sys.stderr)
        return 1

    log = get_logger(__name__)
    settings = app.settings

    try:
        log.info("=" * 60)
        log.info(
            " %s v%s — foundation engine ready",
            settings.app.name,
            settings.app.version,
        )
        log.info("=" * 60)
        log.info(" Project root : %s", app.project_root)
        log.info(
            " Vault dir    : %s",
            app.project_root / settings.paths.vault_dir,
        )
        log.info(
            " Logs dir     : %s",
            app.project_root / settings.paths.logs_dir,
        )
        log.info(" Services     : %d registered", len(app.registry))
        log.info("=" * 60)

        ai = app.registry.get(AIClient)
        try:
            ai.start()
            log.info(" AI engine    : %s @ %s", ai.active_model, settings.ai.ollama_host)
        except Exception:
            log.exception(
                "AI engine could not start — is Ollama running at %s?",
                settings.ai.ollama_host,
            )
            return 1

        if settings.analysis.enabled:
            analysis = app.registry.get(Analyzer)
            analysis.start()
            log.info(" Analysis     : enabled (M4)")

        if settings.docs.enabled:
            app.registry.get(DocumentationGenerator).start()
            log.info(" Docs         : enabled (M5)")

        if settings.graph.enabled:
            app.registry.get(GraphBuilder).start()
            log.info(" Graph        : enabled (M6)")

        if settings.memory.enabled:
            app.registry.get(MemoryEngine).start()
            log.info(" Memory       : enabled (M7)")

        if settings.obsidian.enabled:
            app.registry.get("obsidian").start()
            log.info(" Obsidian     : enabled (M8)")

        if settings.git.enabled:
            app.registry.get("git").start()
            log.info(" Git          : enabled (M9)")

        if settings.intelligence.enabled:
            app.registry.get("intelligence").start()
            log.info(" Intelligence : enabled (M10)")

        if settings.watcher.enabled:
            watcher = app.registry.get(FileWatcher)
            watcher.start()
            log.info(
                "Watcher engine active — monitoring %s",
                ", ".join(settings.watcher.watch_dirs),
            )
            log.info("Press Ctrl+C to stop.")
            watcher.wait_until_stopped()
        else:
            log.info(
                "Watcher disabled — set watcher.enabled=true to monitor "
                "backend/, frontend/, src/, app/."
            )
        return 0
    finally:
        app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
