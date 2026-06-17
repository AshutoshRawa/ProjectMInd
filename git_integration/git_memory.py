"""
git/git_memory.py
=================
Module 9 — Commit storage and retrieval layer.

Bridges the Git Intelligence Engine (M9) with the Memory Engine (M7).
Every summarised commit is stored as a single :class:`~memory.chunker.Chunk`
so that Module 10 (Intelligence Layer) can query commits semantically
(e.g. *"show commits touching auth"*).

Chunk schema
------------
::

    Chunk(
        id         = f"git::commit::{commit.hash}",
        content    = commit.ai_summary,
        chunk_type = "commit",
        metadata   = {
            "file_path":     f"git::commit::{commit.hash}",   # virtual path
            "chunk_type":    "commit",
            "hash":          commit.hash,
            "author":        commit.author,
            "date":          commit.date,
            "files_changed": ", ".join(commit.files_changed),
            "impact_score":  commit.impact_score,
        },
    )

Note: ``file_path`` is set to the virtual path ``git::commit::<hash>``
so :meth:`~memory.memory_store.MemoryStore.delete_by_file` can address
commit chunks independently of code chunks.

Search filtering
----------------
:func:`search_commits` passes ``filter_type="commit"`` (via the
``chunk_type`` metadata field) so results are restricted to commit
chunks only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.logger import get_logger
from git_integration.git_types import CommitInfo
from memory.chunker import Chunk
from memory.memory_store import MemoryStore

if TYPE_CHECKING:
    from memory.semantic_search import SearchResult

log = get_logger(__name__)

# Virtual file_path prefix used for commit chunks so they can be
# isolated from code chunks via where-clause filtering.
_COMMIT_FILE_PREFIX = "git::commit::"


class GitMemory:
    """
    Stores and retrieves git commit chunks from the vector store.

    Parameters
    ----------
    store:
        The shared :class:`~memory.memory_store.MemoryStore` instance.
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def store_commit(self, commit: CommitInfo) -> None:
        """
        Embed *commit.ai_summary* and upsert it into the vector store.

        The chunk ID is stable: re-processing the same hash is a no-op
        (ChromaDB upsert semantics).

        Parameters
        ----------
        commit:
            Fully-summarised :class:`~git.git_types.CommitInfo`.
            ``commit.ai_summary`` must be non-empty.
        """
        if not commit.ai_summary:
            log.warning(
                "[git_memory] commit %s has no ai_summary — skipping store",
                commit.short_hash,
            )
            return

        chunk_id = f"git::commit::{commit.hash}"
        virtual_path = f"{_COMMIT_FILE_PREFIX}{commit.hash}"

        chunk = Chunk(
            id=chunk_id,
            content=commit.ai_summary,
            chunk_type="commit",  # type: ignore[arg-type]  # Chunk.chunk_type is Literal
            metadata={
                "file_path":     virtual_path,
                "hash":          commit.hash,
                "author":        commit.author,
                "date":          commit.date,
                "files_changed": ", ".join(commit.files_changed),
                "impact_score":  commit.impact_score,
                "message":       commit.message[:500],  # cap for metadata size
            },
        )

        self._store.upsert([chunk])
        log.info(
            "[git_memory] stored commit %s (impact=%.2f)",
            commit.short_hash,
            commit.impact_score,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def search_commits(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> list["SearchResult"]:
        """
        Semantic search across stored commit summaries.

        Parameters
        ----------
        query:
            Natural language query (e.g. ``"commits touching auth"``).
        top_k:
            Maximum number of results to return.

        Returns
        -------
        list[SearchResult]
            Ordered by similarity score descending.  Only ``chunk_type="commit"``
            chunks are returned.
        """
        from memory.semantic_search import search  # noqa: PLC0415

        if not query.strip():
            return []

        # We filter by chunk_type=commit in the where clause. ChromaDB
        # uses metadata equality: pass filter_language=None and rely on
        # the internal where dict.
        results = _search_commits_impl(
            query=query,
            store=self._store,
            top_k=top_k,
        )
        log.debug("[git_memory] search '%s' → %d results", query[:50], len(results))
        return results


# ---------------------------------------------------------------------------
# Internal — search with commit-type filter
# ---------------------------------------------------------------------------

def _search_commits_impl(
    query: str,
    *,
    store: MemoryStore,
    top_k: int,
) -> list["SearchResult"]:
    """
    Run semantic search restricted to ``chunk_type == "commit"`` chunks.

    We implement this here (rather than re-using
    :func:`~memory.semantic_search.search`) so we can inject the
    ``where`` clause filter for ``chunk_type`` without adding a
    ``filter_type`` parameter to the generic search function.
    """
    from memory.embedder import embed          # noqa: PLC0415
    from memory.semantic_search import SearchResult, _parse_results, _safe_n_results  # noqa: PLC0415

    vector = embed(query)

    with store._lock:   # noqa: SLF001
        col = store._ensure_client()  # noqa: SLF001
        try:
            raw = col.query(
                query_embeddings=[vector],
                n_results=_safe_n_results(col, top_k),
                where={"chunk_type": "commit"},
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:  # noqa: BLE001
            log.error("[git_memory] commit search failed: %s", exc)
            return []

    return _parse_results(raw)
