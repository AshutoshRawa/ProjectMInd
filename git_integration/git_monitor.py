"""
git/git_monitor.py
==================
Module 9 — Git repository monitor.

Watches a git repository for new commits and publishes
``git.commit`` events on the :class:`~core.event_bus.EventBus`.

Design
------
- Uses **GitPython** (``gitpython`` package) for all git operations.
  Never shells out to ``subprocess`` or ``os.system``.
- A background ``threading.Thread`` polls the HEAD commit every
  ``poll_interval`` seconds (default 30 s) and publishes a
  ``"git.commit"`` event for each new commit discovered since the
  last-seen hash.
- ``get_latest_commit()`` and ``get_commits_since()`` are also available
  as synchronous, on-demand call-sites (e.g. for initial bootstrap).

Published event payload
-----------------------
::

    {
        "commit": CommitInfo,   # fully populated, ai_summary="" (filled by summarizer)
    }

The :class:`~git.commit_summarizer.CommitSummarizer` subscribes to
``"git.commit"`` and enriches the payload with an AI summary before
the :class:`~git.git_memory.GitMemory` stores it.
"""

from __future__ import annotations

import threading
import time
from datetime import timezone
from pathlib import Path
from typing import Any

from core.event_bus import EventBus
from core.logger import get_logger
from git_integration.git_types import CommitInfo, DiffChunk

log = get_logger(__name__)

_EVENT_GIT_COMMIT = "git.commit"
_MAX_DIFF_BYTES = 100_000          # truncate individual file diffs at ~100 KB
_TOKEN_BUDGET_PER_CHUNK = 2_000    # split files > this into sub-chunks

# ---------------------------------------------------------------------------
# GitPython import helper
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# GitPython import
# ---------------------------------------------------------------------------
# Previously, the local `git/` package shadowed the installed `gitpython`
# package (which also exposes itself as `git`).  Renaming this package to
# `git_integration/` eliminates the conflict — gitpython can now be imported
# directly without any sys.path manipulation.

import sys as _sys
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


def _load_gitpython() -> Any:
    """Return the gitpython top-level module.

    Since this package is named ``git_integration`` (not ``git``), there is
    no longer a namespace conflict with the installed ``gitpython`` library.
    """
    import importlib  # noqa: PLC0415
    existing = _sys.modules.get("git")
    if existing is not None and hasattr(existing, "Repo"):
        return existing
    return importlib.import_module("git")


class GitMonitor:
    """
    Polls a git repository for new commits and publishes events.

    Parameters
    ----------
    repo_path:
        Absolute path to the git repository root.
    bus:
        Shared :class:`~core.event_bus.EventBus`.
    poll_interval:
        Seconds between HEAD polls (default 30).
    """

    def __init__(
        self,
        repo_path: str | Path,
        bus: EventBus,
        poll_interval: float = 30.0,
    ) -> None:
        self._repo_path = Path(repo_path).resolve()
        self._bus = bus
        self._poll_interval = poll_interval
        self._last_seen_hash: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._repo: Any = None          # git.Repo, lazily initialised

    # ------------------------------------------------------------------
    # Service lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open the repository and start the polling thread."""
        if self._started:
            return
        self._started = True
        self._repo = self._open_repo()
        if self._repo is None:
            log.error("[git_monitor] could not open repo at %s — polling disabled", self._repo_path)
            return

        # Seed last-seen with current HEAD so we don't replay history on boot.
        try:
            self._last_seen_hash = self._repo.head.commit.hexsha
        except Exception as exc:  # noqa: BLE001
            log.warning("[git_monitor] could not read HEAD: %s", exc)

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="projectmind.module9.git_monitor",
            daemon=True,
        )
        self._thread.start()
        log.info("[git_monitor] started — repo=%s, poll=%.0fs", self._repo_path, self._poll_interval)

    def stop(self) -> None:
        """Signal the polling thread to exit."""
        if not self._started:
            return
        self._started = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log.info("[git_monitor] stopped")

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def get_latest_commit(self) -> CommitInfo | None:
        """
        Return a :class:`~git.git_types.CommitInfo` for the current HEAD,
        or ``None`` if the repository cannot be read.
        """
        repo = self._repo or self._open_repo()
        if repo is None:
            return None
        try:
            return self._commit_to_info(repo.head.commit, repo)
        except Exception as exc:  # noqa: BLE001
            log.error("[git_monitor] get_latest_commit failed: %s", exc)
            return None

    def get_commits_since(self, commit_hash: str) -> list[CommitInfo]:
        """
        Return all commits on the current branch newer than *commit_hash*.

        The result is ordered newest-first (same as ``git log``).
        Returns an empty list if *commit_hash* is not found or the repo
        is empty.

        Parameters
        ----------
        commit_hash:
            Full or abbreviated SHA-1 of the fence commit.  Commits
            **after** this hash are returned; the fence commit itself
            is excluded.
        """
        repo = self._repo or self._open_repo()
        if repo is None:
            return []
        try:
            commits = list(repo.iter_commits(rev=f"{commit_hash}..HEAD"))
            return [self._commit_to_info(c, repo) for c in commits]
        except Exception as exc:  # noqa: BLE001
            log.warning("[git_monitor] get_commits_since(%s) failed: %s", commit_hash, exc)
            return []

    # ------------------------------------------------------------------
    # Internal — polling loop
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._poll_interval)
            if self._stop_event.is_set():
                break
            self._check_for_new_commits()

    def _check_for_new_commits(self) -> None:
        repo = self._repo
        if repo is None:
            return
        try:
            repo.remotes.origin.fetch()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass  # Offline / no remote — still check local HEAD.

        try:
            head_hash = repo.head.commit.hexsha
        except Exception as exc:  # noqa: BLE001
            log.debug("[git_monitor] HEAD read error: %s", exc)
            return

        if head_hash == self._last_seen_hash:
            return

        new_commits = (
            self.get_commits_since(self._last_seen_hash)
            if self._last_seen_hash
            else [self._commit_to_info(repo.head.commit, repo)]
        )

        for info in reversed(new_commits):   # oldest-first so M10 sees chronological order
            log.info("[git_monitor] new commit %s by %s", info.short_hash, info.author)
            self._bus.publish(_EVENT_GIT_COMMIT, {"commit": info})

        self._last_seen_hash = head_hash

    # ------------------------------------------------------------------
    # Internal — repo helpers
    # ------------------------------------------------------------------

    def _open_repo(self) -> Any | None:
        try:
            gitpkg = _load_gitpython()
            repo = gitpkg.Repo(str(self._repo_path), search_parent_directories=False)
            log.debug("[git_monitor] opened repo at %s", self._repo_path)
            return repo
        except Exception as exc:  # noqa: BLE001
            log.error("[git_monitor] failed to open repo: %s", exc)
            return None

    def _commit_to_info(self, commit: Any, repo: Any) -> CommitInfo:
        """Convert a ``git.Commit`` object to a :class:`CommitInfo`."""
        # Files changed in this commit.
        files_changed: list[str] = []
        diff_chunks: list[DiffChunk] = []

        try:
            parent = commit.parents[0] if commit.parents else None
            diffs = parent.diff(commit, create_patch=True) if parent else commit.diff(None, create_patch=True)

            for d in diffs:
                rel_path = d.b_path or d.a_path or ""
                files_changed.append(rel_path)
                raw_diff = self._safe_diff_text(d)
                # Count added/removed lines.
                added   = sum(1 for ln in raw_diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
                removed = sum(1 for ln in raw_diff.splitlines() if ln.startswith("-") and not ln.startswith("---"))

                # Split very large files into sub-chunks.
                sub_chunks = _split_diff_to_chunks(rel_path, raw_diff, added, removed)
                diff_chunks.extend(sub_chunks)
        except Exception as exc:  # noqa: BLE001
            log.debug("[git_monitor] diff parsing failed for %s: %s", commit.hexsha[:8], exc)

        # Date as ISO 8601 UTC.
        committed_dt = commit.committed_datetime.astimezone(timezone.utc)
        date_str = committed_dt.isoformat()

        return CommitInfo(
            hash=commit.hexsha,
            author=f"{commit.author.name} <{commit.author.email}>",
            date=date_str,
            message=commit.message.strip(),
            files_changed=files_changed,
            diff_chunks=diff_chunks,
        )

    @staticmethod
    def _safe_diff_text(diff_item: Any) -> str:
        """Extract and truncate diff text safely."""
        try:
            raw: bytes = diff_item.diff
            if isinstance(raw, bytes):
                text = raw.decode("utf-8", errors="replace")
            else:
                text = str(raw)
        except Exception:  # noqa: BLE001
            text = ""
        return text[:_MAX_DIFF_BYTES]


# ---------------------------------------------------------------------------
# Internal helper — diff splitting
# ---------------------------------------------------------------------------

def _split_diff_to_chunks(
    file_path: str,
    diff_text: str,
    added: int,
    removed: int,
) -> list[DiffChunk]:
    """
    Split a per-file diff into one or more :class:`DiffChunk` objects.

    If the diff's token count is within budget, a single chunk is returned.
    Otherwise the lines are split into overlapping windows of
    ``_TOKEN_BUDGET_PER_CHUNK`` words with 50-word overlap.
    """
    token_count = len(diff_text.split())

    if token_count <= _TOKEN_BUDGET_PER_CHUNK:
        return [DiffChunk(
            file_path=file_path,
            lines_added=added,
            lines_removed=removed,
            content=diff_text,
            token_estimate=token_count,
        )]

    # Sliding-window split.
    words = diff_text.split()
    window = _TOKEN_BUDGET_PER_CHUNK
    overlap = 50
    step = max(1, window - overlap)
    chunks: list[DiffChunk] = []
    i = 0
    while i < len(words):
        window_words = words[i: i + window]
        chunks.append(DiffChunk(
            file_path=file_path,
            lines_added=added if i == 0 else 0,   # only count lines in first chunk
            lines_removed=removed if i == 0 else 0,
            content=" ".join(window_words),
            token_estimate=len(window_words),
        ))
        if i + window >= len(words):
            break
        i += step

    return chunks
