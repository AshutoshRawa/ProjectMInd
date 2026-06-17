"""
memory/semantic_search.py
=========================
High-level semantic search interface over the ProjectMind vector store.

Public API
----------
- :func:`search` — embed *query* and retrieve the top-k most similar
  chunks from the entire collection, with optional language filter.
- :func:`search_by_file` — find chunks in *other* files that are
  semantically similar to chunks inside the given file.

Both functions return :class:`SearchResult` dataclass instances for
type-safe, attribute-accessible results.

Distances → scores
-------------------
ChromaDB returns distances (lower = more similar for cosine distance).
We convert to a **similarity score** in [0, 1] using::

    score = 1 - distance

so callers get intuitive values: 1.0 = identical, 0.0 = orthogonal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger
from memory.embedder import embed
from memory.memory_store import MemoryStore

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """
    A single search hit returned by :func:`search` or :func:`search_by_file`.

    Attributes
    ----------
    chunk_id:
        The stable chunk identifier (``"<file_path>::<type>::<name>"``).
    file_path:
        Absolute path to the source file that contains this chunk.
    content:
        The raw text of the chunk (as stored in ChromaDB).
    score:
        Similarity score in ``[0, 1]``.  Higher = more similar.
    metadata:
        The full metadata dict as stored alongside the vector.
    """

    chunk_id: str
    file_path: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search(
    query: str,
    *,
    store: MemoryStore,
    top_k: int = 5,
    filter_language: str | None = None,
) -> list[SearchResult]:
    """
    Semantic search across the entire ``projectmind_code`` collection.

    Parameters
    ----------
    query:
        Natural-language or code query string.
    store:
        The :class:`~memory.memory_store.MemoryStore` to query.
    top_k:
        Maximum number of results to return.
    filter_language:
        If provided (e.g. ``"python"``), restrict results to chunks whose
        ``metadata["language"]`` matches this value exactly.

    Returns
    -------
    list[SearchResult]
        Ordered by similarity score descending (best match first).
        May be shorter than *top_k* if fewer chunks are stored.
    """
    if not query.strip():
        return []

    vector = embed(query)

    where: dict[str, Any] | None = None
    if filter_language:
        where = {"language": filter_language}

    with store._lock:  # noqa: SLF001 — intentional single-lock access
        col = store._ensure_client()  # noqa: SLF001
        try:
            result = col.query(
                query_embeddings=[vector],
                n_results=_safe_n_results(col, top_k),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:  # noqa: BLE001
            log.error("[semantic_search] query failed: %s", exc)
            return []

    return _parse_results(result)


def search_by_file(
    file_path: str,
    *,
    store: MemoryStore,
    top_k: int = 10,
) -> list[SearchResult]:
    """
    Find chunks in *other* files that are semantically similar to the
    content of *file_path*.

    Strategy
    --------
    1. Fetch up to 3 representative chunks from *file_path* (module +
       first function, if any).
    2. Concatenate their content and embed it as a single composite query.
    3. Run semantic search excluding the source file itself.

    Parameters
    ----------
    file_path:
        Absolute path string matching the stored ``metadata["file_path"]``.
    store:
        The :class:`~memory.memory_store.MemoryStore` to query.
    top_k:
        Maximum number of results (from other files) to return.

    Returns
    -------
    list[SearchResult]
        Results from *other* files, ordered by similarity descending.
    """
    # Step 1: fetch representative chunks from the source file.
    with store._lock:  # noqa: SLF001
        col = store._ensure_client()  # noqa: SLF001
        try:
            own = col.get(
                where={"file_path": file_path},
                include=["documents", "metadatas"],
                limit=3,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "[semantic_search] could not fetch own chunks for %s: %s",
                file_path,
                exc,
            )
            return []

    own_docs: list[str] = own.get("documents") or []
    if not own_docs:
        log.debug("[semantic_search] no chunks found for file=%s", file_path)
        return []

    # Step 2: composite query.
    composite_text = "\n".join(own_docs)
    vector = embed(composite_text)

    # Step 3: search, excluding the source file.
    with store._lock:  # noqa: SLF001
        col = store._ensure_client()  # noqa: SLF001
        try:
            result = col.query(
                query_embeddings=[vector],
                n_results=_safe_n_results(col, top_k + len(own_docs)),
                where={"file_path": {"$ne": file_path}},
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:  # noqa: BLE001
            log.error("[semantic_search] search_by_file query failed: %s", exc)
            return []

    hits = _parse_results(result)
    # Return only top_k after trimming any accidental source-file matches.
    filtered = [h for h in hits if h.file_path != file_path]
    return filtered[:top_k]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_n_results(col: Any, n: int) -> int:
    """Clamp *n* to the number of items in the collection (minimum 1)."""
    total = col.count()
    return max(1, min(n, total))


def _parse_results(raw: dict[str, Any]) -> list[SearchResult]:
    """
    Convert a raw ChromaDB query response into :class:`SearchResult` objects.

    ChromaDB returns lists-of-lists (one list per query vector).  We sent
    exactly one query vector, so we take ``[0]`` from each field.
    """
    ids: list[str] = (raw.get("ids") or [[]])[0]
    docs: list[str] = (raw.get("documents") or [[]])[0]
    metas: list[dict] = (raw.get("metadatas") or [[]])[0]
    dists: list[float] = (raw.get("distances") or [[]])[0]

    results: list[SearchResult] = []
    for cid, doc, meta, dist in zip(ids, docs, metas, dists):
        meta = meta or {}
        score = max(0.0, min(1.0, 1.0 - dist))
        results.append(
            SearchResult(
                chunk_id=cid,
                file_path=meta.get("file_path", ""),
                content=doc or "",
                score=score,
                metadata=meta,
            )
        )

    # Sort by score descending (best first).
    results.sort(key=lambda r: r.score, reverse=True)
    return results
