"""
obsidian/note_builder.py
========================
Assembles enriched Obsidian markdown notes from raw documentation +
graph links + semantic search results.

This module is a **pure transformation layer** — it does no I/O.
Callers pass in content strings and receive a combined markdown string
ready to be handed to :class:`~obsidian.vault_writer.WriteQueue`.

Design rules
------------
- Frontmatter in *doc_markdown* is preserved **exactly** — not parsed,
  not re-serialised.  This avoids round-trip YAML drift.
- ``## Related Files`` section: wiki-links from *graph_links*, one per line.
- ``## Semantic Neighbors`` section: top-3 :class:`~memory.semantic_search.SearchResult`
  items from *related_chunks*, formatted as a bulleted list with score.
- Both appended sections use H2 (``##``) so they appear in Obsidian's
  outline without conflicting with the H1 title in the body.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.logger import get_logger
from obsidian.link_resolver import path_to_wikilink

if TYPE_CHECKING:
    from memory.semantic_search import SearchResult

log = get_logger(__name__)

# Maximum number of semantic neighbors to show.
_MAX_NEIGHBORS = 3


def build_note(
    doc_markdown: str,
    graph_links: list[str],
    related_chunks: list["SearchResult"],
    *,
    vault_root: str = "",
) -> str:
    """
    Assemble an enriched Obsidian note.

    Parameters
    ----------
    doc_markdown:
        The raw markdown produced by Module 5 (docs engine).  May or may not
        include a YAML frontmatter block — either way it is preserved verbatim.
    graph_links:
        List of filesystem paths to files that are direct graph neighbours
        (imports / imported-by) of the subject file.  Each is converted to
        an Obsidian ``[[wiki-link]]``.
    related_chunks:
        Semantic search results from Module 7.  The top
        :data:`_MAX_NEIGHBORS` are appended as a "Semantic Neighbors" section.
    vault_root:
        Vault root path, forwarded to :func:`~obsidian.link_resolver.path_to_wikilink`
        for shortest-path resolution.  Optional — pass empty string to use
        bare filename stems.

    Returns
    -------
    str
        Complete Obsidian-compatible markdown document.

    Examples
    --------
    >>> note = build_note("---\\ntitle: foo\\n---\\n# Foo\\n", ["/vault/bar.md"], [])
    >>> "## Related Files" in note
    True
    >>> "[[bar]]" in note
    True
    """
    parts: list[str] = [doc_markdown.rstrip("\n")]

    # ------------------------------------------------------------------
    # ## Related Files
    # ------------------------------------------------------------------
    related_section = _build_related_section(graph_links, vault_root=vault_root)
    if related_section:
        parts.append(related_section)

    # ------------------------------------------------------------------
    # ## Semantic Neighbors
    # ------------------------------------------------------------------
    neighbors_section = _build_neighbors_section(related_chunks)
    if neighbors_section:
        parts.append(neighbors_section)

    result = "\n\n".join(parts) + "\n"
    log.debug(
        "[note_builder] built note: %d related links, %d semantic neighbors",
        len(graph_links),
        min(len(related_chunks), _MAX_NEIGHBORS),
    )
    return result


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_related_section(graph_links: list[str], *, vault_root: str) -> str:
    """
    Build the ``## Related Files`` section.

    Returns an empty string if *graph_links* is empty.
    """
    if not graph_links:
        return ""

    lines = ["## Related Files", ""]
    for path in graph_links:
        wikilink = path_to_wikilink(path, vault_root)
        lines.append(f"- {wikilink}")

    return "\n".join(lines)


def _build_neighbors_section(related_chunks: list["SearchResult"]) -> str:
    """
    Build the ``## Semantic Neighbors`` section from search results.

    Uses the top :data:`_MAX_NEIGHBORS` results (by score, already sorted
    descending by the search layer).  Returns empty string if no results.
    """
    top = related_chunks[:_MAX_NEIGHBORS]
    if not top:
        return ""

    lines = ["## Semantic Neighbors", ""]
    for result in top:
        from pathlib import Path as _Path  # noqa: PLC0415
        stem = _Path(result.file_path).stem if result.file_path else "unknown"
        score_pct = int(result.score * 100)
        lines.append(f"- [[{stem}]] — {score_pct}% similar")

    return "\n".join(lines)
