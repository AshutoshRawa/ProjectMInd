"""
git/commit_summarizer.py
========================
Module 9 — AI-powered commit summariser.

IMPORTANT: All AI calls go through ``get_ai().complete('commit_summary', ...)``
— never call Ollama or any other LLM directly from this module.

Summarisation strategy
----------------------
Small diffs (≤ 2 000 tokens total)
    Single call to ``get_ai().complete('commit_summary', …)`` with the full
    diff content.

Large diffs (> 2 000 tokens total)
    **Hierarchical summarisation**:

    1. Summarise each :class:`~git.git_types.DiffChunk` individually with
       ``get_ai().complete('commit_summary', …)``.
    2. Combine the chunk summaries into a single "summaries-of-summaries"
       document.
    3. Summarise the combined document with a second
       ``get_ai().complete('commit_summary', …)`` call.

Impact score formula
--------------------
::

    base     = min(files_changed_count * 0.2, 0.6)
    lines    = min((lines_added + lines_removed) / 500 * 0.3, 0.3)
    score    = min(base + lines, 1.0)

The ``avg_complexity`` term is added when the caller supplies a
*graph_complexity* value (float in [0, 1]) derived from Module 6's
node-complexity metadata.  If not supplied, the complexity term is 0.

Public API
----------
- :func:`summarize` — the primary entry point.
- :func:`calculate_impact_score` — exposed for testing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.logger import get_logger
from git_integration.git_types import CommitInfo

if TYPE_CHECKING:
    from ai.ai_manager import AIManager

log = get_logger(__name__)

_TOKEN_THRESHOLD = 2_000    # chars-worth of tokens; word-count approximation


def summarize(
    commit: CommitInfo,
    *,
    ai: "AIManager",
    graph_complexity: float | None = None,
) -> str:
    """
    Produce a plain-English summary for *commit* and update it in-place.

    Uses ``ai.complete('commit_summary', …)`` — never Ollama directly.

    Parameters
    ----------
    commit:
        The commit to summarise.  ``commit.ai_summary`` and
        ``commit.impact_score`` are mutated by this function.
    ai:
        The process-wide :class:`~ai.ai_manager.AIManager` singleton.
        Callers should pass ``get_ai()`` here.
    graph_complexity:
        Optional average complexity score (0–1) for the files changed,
        derived from Module 6's graph metadata.  Used in impact scoring.

    Returns
    -------
    str
        The generated summary (also stored in ``commit.ai_summary``).
    """
    total_tokens = commit.total_tokens

    if total_tokens <= _TOKEN_THRESHOLD or not commit.diff_chunks:
        summary = _summarize_single(commit, ai=ai)
    else:
        summary = _summarize_hierarchical(commit, ai=ai)

    commit.ai_summary = summary
    commit.impact_score = calculate_impact_score(
        commit,
        graph_complexity=graph_complexity,
    )

    log.info(
        "[commit_summarizer] %s summarised — tokens=%d impact=%.2f",
        commit.short_hash,
        total_tokens,
        commit.impact_score,
    )
    return summary


def calculate_impact_score(
    commit: CommitInfo,
    *,
    graph_complexity: float | None = None,
) -> float:
    """
    Compute a normalised impact score in ``[0.0, 1.0]``.

    Formula
    -------
    ::

        base_files  = min(len(files_changed) * 0.2, 0.6)
        complexity  = (graph_complexity or 0.0) * 0.5   (capped contribution)
        lines_term  = min((lines_added + lines_removed) / 500 * 0.3, 0.3)
        score       = min(base_files + complexity * 0.5 + lines_term, 1.0)

    The weights are chosen so that:
    - A 3-file commit with moderate complexity sits around 0.6.
    - A 1-line cosmetic fix scores < 0.1.
    - A 10-file refactor with high complexity reaches 1.0.

    Parameters
    ----------
    commit:
        The commit whose impact is being scored.
    graph_complexity:
        Optional average complexity of changed files from Module 6,
        in ``[0.0, 1.0]``.

    Returns
    -------
    float
        Impact score in ``[0.0, 1.0]``.
    """
    n_files = len(commit.files_changed)
    base_files = min(n_files * 0.2, 0.6)

    complexity_term = (graph_complexity or 0.0) * 0.5

    total_lines = commit.total_lines_added + commit.total_lines_removed
    lines_term = min(total_lines / 500 * 0.3, 0.3)

    raw = base_files + complexity_term + lines_term
    return round(min(raw, 1.0), 4)


# ---------------------------------------------------------------------------
# Internal — single-pass summarisation
# ---------------------------------------------------------------------------

def _summarize_single(commit: CommitInfo, *, ai: "AIManager") -> str:
    """
    Summarise a commit whose total diff fits within the token budget.

    Uses the ``commit_summary`` prompt registered in Module 3's
    :class:`~ai.prompt_registry.PromptRegistry`.
    """
    diff_text = "\n\n".join(c.content for c in commit.diff_chunks) if commit.diff_chunks else "(no diff)"

    return ai.complete(
        "commit_summary",
        {
            "commit_hash": commit.short_hash,
            "author": commit.author,
            "files_changed": ", ".join(commit.files_changed) or "(none)",
            "diff": _truncate(diff_text, max_words=_TOKEN_THRESHOLD),
        },
    )


# ---------------------------------------------------------------------------
# Internal — hierarchical summarisation
# ---------------------------------------------------------------------------

def _summarize_hierarchical(commit: CommitInfo, *, ai: "AIManager") -> str:
    """
    Two-stage hierarchical summarisation for large diffs.

    Stage 1: summarise each DiffChunk individually.
    Stage 2: combine all chunk summaries and summarise again.
    """
    log.debug(
        "[commit_summarizer] hierarchical mode — %d chunks, %d tokens",
        len(commit.diff_chunks),
        commit.total_tokens,
    )

    # Stage 1 — per-chunk summaries.
    chunk_summaries: list[str] = []
    for i, chunk in enumerate(commit.diff_chunks):
        try:
            summary = ai.complete(
                "commit_summary",
                {
                    "commit_hash": f"{commit.short_hash}[chunk {i + 1}/{len(commit.diff_chunks)}]",
                    "author": commit.author,
                    "files_changed": chunk.file_path,
                    "diff": _truncate(chunk.content, max_words=_TOKEN_THRESHOLD),
                },
            )
            chunk_summaries.append(f"[{chunk.file_path}]: {summary}")
        except Exception as exc:  # noqa: BLE001
            log.warning("[commit_summarizer] chunk %d summary failed: %s", i, exc)
            chunk_summaries.append(f"[{chunk.file_path}]: (summary unavailable)")

    # Stage 2 — summarise all chunk summaries.
    combined = "\n\n".join(chunk_summaries)
    final_summary = ai.complete(
        "commit_summary",
        {
            "commit_hash": commit.short_hash,
            "author": commit.author,
            "files_changed": ", ".join(commit.files_changed),
            "diff": f"[Hierarchical summary of {len(chunk_summaries)} chunks]\n\n{combined}",
        },
    )
    return final_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, max_words: int) -> str:
    """Return *text* truncated to *max_words* words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "\n… [truncated]"
