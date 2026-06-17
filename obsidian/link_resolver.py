"""
obsidian/link_resolver.py
=========================
Utilities for converting filesystem paths into Obsidian wiki-links.

Obsidian's **shortest-path format** means that if ``notes/foo.md`` is
unambiguous within the vault, you can write ``[[foo]]`` instead of
``[[notes/foo]]``.  This module implements that resolution logic.

Public API
----------
- :func:`path_to_wikilink` — single path → ``"[[stem]]"``
- :func:`resolve_links`    — list of paths → list of ``"[[stem]]"`` strings

Both functions accept absolute or relative strings and are pure (no I/O).
"""

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)


def path_to_wikilink(path: str, vault_root: str) -> str:
    """
    Convert a filesystem *path* to an Obsidian ``[[wikilink]]``.

    Strategy
    --------
    1. Resolve *path* relative to *vault_root*.
    2. Use Obsidian's shortest-path convention: if the filename stem is
       unique within the vault (the typical case), emit ``[[stem]]``.
    3. If *path* is outside *vault_root*, fall back to the bare filename
       stem so the link is at least meaningful.

    Parameters
    ----------
    path:
        Absolute or relative path to a markdown file or source file.
    vault_root:
        Absolute path to the Obsidian vault root directory.

    Returns
    -------
    str
        An Obsidian wiki-link string, e.g. ``"[[my-note]]"``.

    Examples
    --------
    >>> path_to_wikilink("/vault/Architecture/service.md", "/vault")
    '[[service]]'
    >>> path_to_wikilink("/src/core/config.py", "/vault")
    '[[config]]'
    """
    target = Path(path).resolve()
    root   = Path(vault_root).resolve()

    try:
        relative = target.relative_to(root)
        # If the file is directly in a section folder the stem is sufficient.
        stem = relative.stem
    except ValueError:
        # Path is outside the vault — just use the filename stem.
        stem = target.stem

    return f"[[{stem}]]"


def resolve_links(paths: list[str], vault_root: str = "") -> list[str]:
    """
    Convert a list of paths to Obsidian wiki-links.

    Duplicate stems are disambiguated by appending the parent folder name
    (e.g. ``[[utils]]`` becomes ``[[core/utils]]`` and ``[[watcher/utils]]``).

    Parameters
    ----------
    paths:
        List of file paths (absolute or relative strings).
    vault_root:
        Vault root for shortest-path resolution.  Pass an empty string to
        always use bare filename stems.

    Returns
    -------
    list[str]
        One wiki-link per input path, in the same order.

    Examples
    --------
    >>> resolve_links(["/vault/A/utils.md", "/vault/B/utils.md"], "/vault")
    ['[[A/utils]]', '[[B/utils]]']
    """
    if not paths:
        return []

    # First pass: compute (stem, path) for each entry.
    stems: list[str] = []
    for p in paths:
        target = Path(p)
        stems.append(target.stem)

    # Detect duplicate stems.
    from collections import Counter
    stem_count = Counter(stems)

    result: list[str] = []
    root = Path(vault_root).resolve() if vault_root else None

    for path, stem in zip(paths, stems):
        target = Path(path).resolve()

        if stem_count[stem] > 1:
            # Disambiguate: use parent/stem.
            if root is not None:
                try:
                    rel = target.relative_to(root)
                    parts = list(rel.parts)
                    if len(parts) >= 2:
                        link_text = f"{parts[-2]}/{rel.stem}"
                    else:
                        link_text = rel.stem
                except ValueError:
                    link_text = f"{target.parent.name}/{stem}"
            else:
                link_text = f"{target.parent.name}/{stem}"
        else:
            link_text = stem

        result.append(f"[[{link_text}]]")

    log.debug("[link_resolver] resolved %d links", len(result))
    return result
