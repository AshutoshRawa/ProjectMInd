"""
obsidian/
=========
**Module 8 — Obsidian Integration Engine**

Provides the complete vault I/O pipeline for ProjectMind:

- :mod:`obsidian.markdown`        — YAML front-matter + body composition
- :mod:`obsidian.vault`           — directory structure and note I/O
- :mod:`obsidian.vault_writer`    — serialised priority-queue writer
- :mod:`obsidian.note_builder`    — enriched note assembly
- :mod:`obsidian.link_resolver`   — path → ``[[wikilink]]`` conversion
- :mod:`obsidian.vault_index`     — startup scan + incremental note index
- :mod:`obsidian.obsidian_engine` — event-driven orchestration service

Usage
-----
.. code-block:: python

    from obsidian import (
        VaultManager,
        WriteQueue, WriteTask, Priority,
        VaultIndex,
        ObsidianEngine,
        build_note,
        path_to_wikilink, resolve_links,
    )
"""

from __future__ import annotations

from obsidian.link_resolver import path_to_wikilink, resolve_links
from obsidian.markdown import build_note_frontmatter, compose_note, parse_frontmatter
from obsidian.note_builder import build_note
from obsidian.obsidian_engine import ObsidianEngine
from obsidian.vault import VaultManager
from obsidian.vault_index import VaultIndex
from obsidian.vault_writer import Priority, WriteQueue, WriteTask

__all__ = [
    # Legacy
    "VaultManager",
    "build_note_frontmatter",
    "compose_note",
    "parse_frontmatter",
    # Module 8 additions
    "WriteQueue",
    "WriteTask",
    "Priority",
    "VaultIndex",
    "ObsidianEngine",
    "build_note",
    "path_to_wikilink",
    "resolve_links",
]
