"""
main.py
=======
ProjectMind entry point.

Run with::

    python main.py

Module 1 bootstraps config, logging, vault, and the service registry.
Module 2 adds an optional long-running filesystem watcher — enable it in
``config/config.yaml`` (``watcher.enabled: true``) or via
``PROJECTMIND_WATCHER__ENABLED=true``.
"""

from __future__ import annotations

import sys

from core.bootstrap import bootstrap
from core.exceptions import ProjectMindError
from core.interfaces import FileWatcher
from core.logger import get_logger


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
