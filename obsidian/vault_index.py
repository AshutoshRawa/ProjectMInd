"""
obsidian/vault_index.py
=======================
In-memory index of all markdown notes in the Obsidian vault.

Responsibilities
----------------
- **Startup scan**: walk the vault root on instantiation and build a
  ``{source_file_path → note_path}`` mapping so the obsidian engine can
  quickly find the note for any source file without hitting the filesystem.
- **Incremental update**: :meth:`VaultIndex.update` keeps the index in sync
  as the :class:`~obsidian.vault_writer.WriteQueue` writes or deletes notes.
- **Lookup**: :meth:`exists` and :meth:`find_note` expose the index to
  callers without exposing the internal dict.

Thread safety
-------------
All public methods are protected by an ``RLock`` so they can be called from
both the EventBus handler thread and the WriteQueue worker thread.

Index key convention
--------------------
The index maps the **source file path** (the Python/JS/TS file being
documented) to the **vault note path** (the ``.md`` file in the vault).
The mapping is derived from the note's filename stem, which the docs engine
sets to match the source file's stem (e.g. ``config.py`` → ``config.md``).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Literal

from core.logger import get_logger
from core.utils import ensure_dir

log = get_logger(__name__)

Operation = Literal["write", "delete", "mkdir"]


class VaultIndex:
    """
    Scanned, in-memory index of vault notes.

    Parameters
    ----------
    vault_root:
        Absolute path to the Obsidian vault root directory.  Scanned
        recursively for ``.md`` files on construction.
    """

    def __init__(self, vault_root: str | Path) -> None:
        self._root = Path(vault_root).resolve()
        self._lock = threading.RLock()
        # Mapping: stem (lowercase) → absolute note path
        self._stem_index: dict[str, Path] = {}
        # Mapping: source_file_path (str) → absolute note path
        self._source_index: dict[str, Path] = {}

        self._scan()

    # ------------------------------------------------------------------
    # Startup scan
    # ------------------------------------------------------------------

    def _scan(self) -> None:
        """Walk *vault_root* and index every ``.md`` file by stem."""
        ensure_dir(self._root)
        count = 0
        with self._lock:
            self._stem_index.clear()
            for md_path in self._root.rglob("*.md"):
                self._stem_index[md_path.stem.lower()] = md_path
                count += 1
        log.info("[vault_index] scanned %d note(s) in %s", count, self._root)

    def rescan(self) -> None:
        """Re-scan the vault root.  Useful after bulk imports."""
        self._scan()

    # ------------------------------------------------------------------
    # Incremental update
    # ------------------------------------------------------------------

    def update(
        self,
        path: str | Path,
        operation: Operation,
        *,
        source_file_path: str | None = None,
    ) -> None:
        """
        Update the index after a write operation.

        Parameters
        ----------
        path:
            The vault path that was written or deleted (must be ``.md``
            for a meaningful index update; non-md paths are silently ignored).
        operation:
            ``"write"`` — add/update entry.
            ``"delete"`` — remove entry.
            ``"mkdir"``  — no-op (directories are not indexed).
        source_file_path:
            If supplied, the index also stores a direct mapping from the
            source file path to this note path.
        """
        note_path = Path(path).resolve()

        if note_path.suffix.lower() != ".md":
            return  # Only index markdown files.

        stem = note_path.stem.lower()

        with self._lock:
            if operation == "write":
                self._stem_index[stem] = note_path
                if source_file_path:
                    self._source_index[source_file_path] = note_path
                log.debug("[vault_index] indexed note: %s", note_path)
            elif operation == "delete":
                self._stem_index.pop(stem, None)
                # Remove any source→note mapping that pointed here.
                stale = [k for k, v in self._source_index.items() if v == note_path]
                for k in stale:
                    del self._source_index[k]
                log.debug("[vault_index] removed note from index: %s", note_path)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def exists(self, path: str) -> bool:
        """
        Return ``True`` if *path* is indexed AND physically exists on disk.

        *path* can be:
        - An absolute note path (e.g. ``/vault/Architecture/config.md``)
        - A source file path previously registered via ``source_file_path``
        """
        note = self._resolve(path)
        return note is not None and note.exists()

    def find_note(self, file_path: str) -> str | None:
        """
        Return the absolute vault note path for *file_path*, or ``None``.

        Lookup order:
        1. Direct source→note mapping (fastest).
        2. Stem match (``config.py`` → looks for ``config.md``).
        3. Returns ``None`` if not found.

        Parameters
        ----------
        file_path:
            Absolute source file path (e.g. ``/project/core/config.py``).
        """
        note = self._resolve(file_path)
        return str(note) if note is not None else None

    def all_notes(self) -> list[str]:
        """Return all indexed note paths as strings."""
        with self._lock:
            return [str(p) for p in self._stem_index.values()]

    def note_count(self) -> int:
        """Return the number of indexed notes."""
        with self._lock:
            return len(self._stem_index)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve(self, path: str) -> Path | None:
        """
        Resolve *path* to an indexed note path.

        Tries direct source mapping first, then stem-based lookup.
        """
        with self._lock:
            # 1. Direct source→note mapping.
            if path in self._source_index:
                return self._source_index[path]

            # 2. If *path* looks like an existing note path, look it up.
            candidate = Path(path).resolve()
            if candidate.suffix.lower() == ".md":
                stem = candidate.stem.lower()
                return self._stem_index.get(stem)

            # 3. Stem-based match: strip extension and search.
            stem = Path(path).stem.lower()
            return self._stem_index.get(stem)
