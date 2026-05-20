"""
main.py
=======
ProjectMind entry point.

Run with::

    python main.py

In Module 1 there are no long-running services yet, so ``main`` simply:

1. Bootstraps the application (config + logging + vault + registry).
2. Prints a status report.
3. Exits cleanly.

Future modules (watcher, AI, analysis…) will hook into the
:class:`~core.bootstrap.Application` returned here and turn ``main``
into a long-running process.
"""

from __future__ import annotations

import sys

from core.bootstrap import bootstrap
from core.exceptions import ProjectMindError
from core.logger import get_logger


def main() -> int:
    """Run the ProjectMind foundation engine.  Returns a process exit code."""
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
        log.info(" %s v%s — foundation engine ready",
                 settings.app.name, settings.app.version)
        log.info("=" * 60)
        log.info(" Project root : %s", app.project_root)
        log.info(" Vault dir    : %s", app.project_root / settings.paths.vault_dir)
        log.info(" Logs dir     : %s", app.project_root / settings.paths.logs_dir)
        log.info(" Services     : %d registered", len(app.registry))
        log.info("=" * 60)
        log.info("Module 1 has no runtime loop yet — exiting cleanly.")
        return 0
    finally:
        # Always run shutdown hooks, even if the body above raises.
        app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
