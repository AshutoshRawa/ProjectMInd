"""
obsidian/vault.py
=================
Obsidian-compatible vault manager.

The vault is the long-term knowledge store for ProjectMind.  It is a
plain directory of markdown files arranged into well-known sections
(``Architecture``, ``Features``, …).  Because the format is plain text
the user can open the same directory in Obsidian and benefit from
backlinks, graph view, etc., for free.

This module owns:
- creating the section directories on bootstrap
- writing notes with default front-matter merged in
- reading notes back as ``(frontmatter, body)`` tuples
- enumerating notes per section

It deliberately does **not** know about graphs, AI, or watching — those
belong to later modules and will *consume* this layer via the
:class:`core.interfaces.NoteStore` protocol.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from core import (
    VaultError,
    VaultFrontmatterSettings,
    atomic_write_text,
    ensure_dir,
    get_logger,
    now_iso,
    slugify,
)
from obsidian.markdown import compose_note, parse_frontmatter

_log = get_logger(__name__)


class VaultManager:
    """
    Filesystem-backed Obsidian vault.

    Parameters
    ----------
    root:
        Absolute path to the vault directory.  Created if absent.
    sections:
        List of section folder names.  Created on :meth:`initialize`.
    frontmatter:
        Default front-matter merged into every note write.  Per-call
        ``extras`` always win over these defaults.
    """

    def __init__(
        self,
        root: Path,
        sections: list[str],
        frontmatter: VaultFrontmatterSettings,
    ) -> None:
        self.root = Path(root)
        self.sections = list(sections)
        self._default_frontmatter = frontmatter

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Create the vault root and all configured section directories."""
        ensure_dir(self.root)
        for section in self.sections:
            ensure_dir(self.root / section)
        # An Obsidian "vault marker" — empty but signals to Obsidian that
        # this directory is a vault root.  Harmless if Obsidian is not
        # installed.
        marker = self.root / ".obsidian"
        ensure_dir(marker)
        _log.debug("Vault initialised: root=%s sections=%s", self.root, self.sections)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def path_for(self, section: str, name: str | None = None) -> Path:
        """
        Return the filesystem path for *section* (and optionally *name*).

        *name* is slugified and given the ``.md`` extension if the
        caller did not supply one.
        """
        self._require_section(section)
        section_dir = self.root / section
        if name is None:
            return section_dir
        filename = name if name.endswith(".md") else f"{slugify(name)}.md"
        return section_dir / filename

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    def write_note(
        self,
        section: str,
        name: str,
        body: str,
        frontmatter_extras: dict[str, Any] | None = None,
    ) -> Path:
        """
        Persist a markdown note.

        Default front-matter (author/tags/status) plus a ``created`` and
        ``updated`` timestamp are merged with *frontmatter_extras*.
        Returns the absolute path written.
        """
        path = self.path_for(section, name)
        existing_created: str | None = None
        if path.exists():
            existing_fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            existing_created = existing_fm.get("created")

        fm: dict[str, Any] = {
            **asdict(self._default_frontmatter),
            "created": existing_created or now_iso(),
            "updated": now_iso(),
        }
        if frontmatter_extras:
            fm.update(frontmatter_extras)

        content = compose_note(fm, body)
        atomic_write_text(path, content)
        _log.debug("Wrote note %s/%s (%d bytes)", section, path.name, len(content))
        return path

    def read_note(self, section: str, name: str) -> tuple[dict[str, Any], str]:
        """Return ``(frontmatter, body)`` for the given note."""
        path = self.path_for(section, name)
        if not path.exists():
            raise VaultError(f"Note not found: {path}")
        return parse_frontmatter(path.read_text(encoding="utf-8"))

    def note_exists(self, section: str, name: str) -> bool:
        return self.path_for(section, name).exists()

    def list_notes(self, section: str) -> list[str]:
        """Return the file names (without path) of every ``.md`` in *section*."""
        section_dir = self.path_for(section)
        if not section_dir.exists():
            return []
        return sorted(p.name for p in section_dir.glob("*.md"))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_section(self, section: str) -> None:
        if section not in self.sections:
            raise VaultError(
                f"Unknown vault section {section!r}. "
                f"Configured sections: {self.sections}"
            )
