"""
watcher/filters.py
==================
Path filtering for the Watcher Engine.

Decides whether a filesystem path should be observed or ignored before
any event is logged or forwarded.  Combines:

- configured watch extensions (``.py``, ``.ts``, …)
- directory-name blocklist (``node_modules``, ``.git``, …)
- optional glob patterns from config (``**/__pycache__/**``, …)
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from core.config import WatcherSettings


# Default directory names skipped anywhere in a watched tree.
DEFAULT_IGNORE_DIR_NAMES: frozenset[str] = frozenset({
    "node_modules",
    ".git",
    "__pycache__",
    "pycache",
    "dist",
    "build",
    "venv",
    ".venv",
    ".next",
    "coverage",
})


class PathFilter:
    """
    Stateless filter built from :class:`~core.config.WatcherSettings`.

    Parameters
    ----------
    settings:
        Watcher section of the application config.
    project_root:
        Resolved project root — used to ignore ProjectMind's own runtime
        dirs (logs, vault) even when they appear under a watch tree.
    """

    def __init__(
        self,
        settings: WatcherSettings,
        project_root: Path,
    ) -> None:
        self._extensions = {
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            for ext in settings.watch_extensions
        }
        self._ignore_dir_names = DEFAULT_IGNORE_DIR_NAMES | frozenset(
            settings.ignore_dirs
        )
        self._ignore_patterns = list(settings.ignore_patterns)
        self._project_root = project_root.resolve()

        # Always skip our own runtime artefacts when paths are under root.
        self._runtime_dirs = {
            (self._project_root / "logs").resolve(),
            (self._project_root / "vault").resolve(),
        }

    def should_watch(self, path: Path) -> bool:
        """
        Return ``True`` if *path* is eligible for observation.

        Directories may pass if they are not themselves ignored (we still
        recurse into them; individual files are filtered on events).
        """
        resolved = path.resolve()

        if resolved.is_dir():
            return not self._is_ignored_path(resolved)

        return self.is_allowed_file(resolved)

    def is_allowed_file(self, path: Path) -> bool:
        """
        Return ``True`` if this path should produce events.

        We intentionally do **not** require the path to exist on disk —
        delete events arrive after the file is already gone.
        """
        resolved = path.resolve()
        if self._is_ignored_path(resolved):
            return False
        return resolved.suffix.lower() in self._extensions

    def _is_ignored_path(self, path: Path) -> bool:
        """Shared ignore logic for files and directories."""
        resolved = path.resolve()

        # Blocklisted directory segment anywhere in the ancestry.
        for part in resolved.parts:
            if part in self._ignore_dir_names:
                return True

        # ProjectMind runtime directories (logs, vault).
        for runtime in self._runtime_dirs:
            try:
                resolved.relative_to(runtime)
                return True
            except ValueError:
                pass

        # User-supplied glob patterns (POSIX-style, case-sensitive).
        posix = resolved.as_posix()
        for pattern in self._ignore_patterns:
            if fnmatch.fnmatch(posix, pattern):
                return True
            # Also try matching just the filename for simple patterns.
            if fnmatch.fnmatch(resolved.name, pattern):
                return True

        return False
