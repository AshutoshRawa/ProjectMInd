"""
memory/memory_store.py
======================
Persistent vector store backed by ChromaDB.

Responsibilities
----------------
- Maintain a single ChromaDB ``PersistentClient`` pointed at the path
  defined in ``config.memory.chroma_db_path`` (falls back to
  ``<project_root>/.chroma``).
- All chunk embeddings live in one collection: ``'projectmind_code'``.
- Expose three operations:
    * :meth:`MemoryStore.upsert` — embed a batch of :class:`~memory.chunker.Chunk` objects
      and store them (delete-then-add semantics are handled by the caller;
      this method only inserts/replaces).
    * :meth:`MemoryStore.delete_by_file` — remove every chunk whose
      ``metadata["file_path"]`` matches *file_path*.
    * :meth:`MemoryStore.get_existing_ids` — return the set of chunk ids
      already stored for a given file path.

Thread safety
-------------
ChromaDB's ``PersistentClient`` is not guaranteed to be re-entrant across
threads, so all public methods are guarded by a ``threading.Lock``.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.logger import get_logger
from memory.chunker import Chunk
from memory.embedder import embed_batch

if TYPE_CHECKING:
    import chromadb
    from chromadb import Collection

log = get_logger(__name__)

_COLLECTION_NAME = "projectmind_code"
_DEFAULT_CHROMA_DIR = ".chroma"


# ---------------------------------------------------------------------------
# MemoryStore
# ---------------------------------------------------------------------------

class MemoryStore:
    """
    Thin wrapper around a ChromaDB persistent collection.

    Parameters
    ----------
    chroma_db_path:
        Absolute (or relative-to-cwd) path where ChromaDB persists data.
        Created automatically if it does not exist.
    """

    def __init__(self, chroma_db_path: str | Path | None = None) -> None:
        self._path = Path(chroma_db_path or _DEFAULT_CHROMA_DIR).resolve()
        self._lock = threading.Lock()
        self._client: "chromadb.PersistentClient | None" = None
        self._collection: "Collection | None" = None

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def _ensure_client(self) -> "Collection":
        """Lazily initialise the ChromaDB client + collection."""
        if self._collection is not None:
            return self._collection

        try:
            import chromadb  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "chromadb is not installed. Run: pip install chromadb"
            ) from exc

        self._path.mkdir(parents=True, exist_ok=True)
        log.info("[memory_store] opening ChromaDB at %s", self._path)
        self._client = chromadb.PersistentClient(path=str(self._path))
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            # Cosine distance gives better semantic similarity ranking.
            metadata={"hnsw:space": "cosine"},
        )
        log.info(
            "[memory_store] collection '%s' ready (%d items)",
            _COLLECTION_NAME,
            self._collection.count(),
        )
        return self._collection

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert(self, chunks: list[Chunk]) -> None:
        """
        Embed *chunks* and upsert them into the collection.

        ChromaDB's ``upsert`` replaces an existing document if the id
        matches, so callers do **not** need to delete first for a single
        id — but :meth:`delete_by_file` is called by :mod:`memory_updater`
        before calling this method to ensure stale chunks are removed.

        Parameters
        ----------
        chunks:
            Non-empty list of :class:`~memory.chunker.Chunk` objects.
            Empty list is a no-op.
        """
        if not chunks:
            return

        texts = [c.content for c in chunks]
        vectors = embed_batch(texts)

        ids = [c.id for c in chunks]
        metadatas: list[dict[str, Any]] = []
        for c in chunks:
            # ChromaDB metadata values must be str | int | float | bool.
            safe_meta: dict[str, Any] = {}
            for k, v in c.metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    safe_meta[k] = v
                elif isinstance(v, list):
                    # Serialize lists as comma-joined strings.
                    safe_meta[k] = ", ".join(str(x) for x in v)
                else:
                    safe_meta[k] = str(v)
            # Always store chunk_type in metadata for filtering.
            safe_meta["chunk_type"] = c.chunk_type
            metadatas.append(safe_meta)

        with self._lock:
            col = self._ensure_client()
            col.upsert(
                ids=ids,
                embeddings=vectors,
                documents=texts,
                metadatas=metadatas,
            )

        log.debug("[memory_store] upserted %d chunks", len(chunks))

    def delete_by_file(self, file_path: str) -> None:
        """
        Remove **all** chunks whose ``metadata.file_path`` matches
        *file_path*.

        Parameters
        ----------
        file_path:
            Absolute path string stored in chunk metadata — must match
            exactly the value used during :meth:`upsert`.
        """
        with self._lock:
            col = self._ensure_client()
            # Query for existing IDs first; ChromaDB's ``delete`` with a
            # ``where`` clause is the most efficient approach.
            try:
                col.delete(where={"file_path": file_path})
                log.debug("[memory_store] deleted chunks for file=%s", file_path)
            except Exception as exc:  # noqa: BLE001
                # Log but do not raise — deletion failure is non-fatal;
                # the subsequent upsert will replace any stale vectors.
                log.warning(
                    "[memory_store] delete_by_file failed for %s: %s",
                    file_path,
                    exc,
                )

    def get_existing_ids(self, file_path: str) -> set[str]:
        """
        Return the set of chunk IDs currently stored for *file_path*.

        Useful for diffing: callers can detect which chunks were removed
        between two versions of the same file.

        Parameters
        ----------
        file_path:
            Absolute path string stored in chunk metadata.

        Returns
        -------
        set[str]
            Possibly empty.  Never raises.
        """
        with self._lock:
            col = self._ensure_client()
            try:
                result = col.get(where={"file_path": file_path}, include=[])
                return set(result.get("ids", []))
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "[memory_store] get_existing_ids failed for %s: %s",
                    file_path,
                    exc,
                )
                return set()

    def count(self) -> int:
        """Return the total number of stored chunks."""
        with self._lock:
            col = self._ensure_client()
            return col.count()
