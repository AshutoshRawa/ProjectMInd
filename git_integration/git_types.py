"""
git/git_types.py
================
Immutable data types shared across all sub-modules of Module 9.

Design notes
------------
- All fields use primitive types (str, int, float, list) so instances can
  be freely serialised to JSON or stored in ChromaDB metadata without
  additional conversion.
- ``impact_score`` is in [0.0, 1.0] and is computed by
  :mod:`git.commit_summarizer` after the AI summary is produced.
- ``token_estimate`` in :class:`DiffChunk` is a fast word-count
  approximation (``len(content.split())``), not an exact BPE count.
  It is accurate enough to decide whether hierarchical summarisation is
  needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# DiffChunk
# ---------------------------------------------------------------------------


@dataclass
class DiffChunk:
    """
    A single contiguous fragment of a git diff.

    One ``DiffChunk`` typically corresponds to one modified file, but very
    large files may be split into multiple chunks by
    :func:`~git.git_monitor.GitMonitor._parse_diff`.

    Attributes
    ----------
    file_path:
        Relative path of the file in the repository (as reported by git).
    lines_added:
        Number of ``+`` lines in this chunk's diff text.
    lines_removed:
        Number of ``-`` lines in this chunk's diff text.
    content:
        The raw unified-diff text for this chunk.
    token_estimate:
        Approximate word-count of *content*.  Used by the summariser to
        decide whether hierarchical summarisation is necessary.
    """

    file_path: str
    lines_added: int
    lines_removed: int
    content: str
    token_estimate: int = field(default=0)

    def __post_init__(self) -> None:
        if self.token_estimate == 0:
            self.token_estimate = len(self.content.split())


# ---------------------------------------------------------------------------
# CommitInfo
# ---------------------------------------------------------------------------


@dataclass
class CommitInfo:
    """
    Everything ProjectMind knows about a single git commit.

    Attributes
    ----------
    hash:
        Full 40-character SHA-1 hex string.
    author:
        ``"Name <email>"`` string as reported by GitPython.
    date:
        ISO 8601 datetime string (UTC), e.g. ``"2024-06-14T09:00:00+00:00"``.
    message:
        Full commit message (subject + body, if any).
    files_changed:
        List of relative file paths touched by this commit.
    diff_chunks:
        One :class:`DiffChunk` per changed file (or more for large files).
        Populated by :class:`~git.git_monitor.GitMonitor`.
    ai_summary:
        Plain-English summary produced by :mod:`git.commit_summarizer`.
        Empty string until filled.
    impact_score:
        Float in ``[0.0, 1.0]``.  Higher = more impactful commit.
        Zero until calculated by :mod:`git.commit_summarizer`.
    """

    hash: str
    author: str
    date: str
    message: str
    files_changed: list[str] = field(default_factory=list)
    diff_chunks: list[DiffChunk] = field(default_factory=list)
    ai_summary: str = ""
    impact_score: float = 0.0

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def total_lines_added(self) -> int:
        return sum(c.lines_added for c in self.diff_chunks)

    @property
    def total_lines_removed(self) -> int:
        return sum(c.lines_removed for c in self.diff_chunks)

    @property
    def total_tokens(self) -> int:
        """Approximate token count across all diff chunks."""
        return sum(c.token_estimate for c in self.diff_chunks)

    @property
    def short_hash(self) -> str:
        return self.hash[:8]
