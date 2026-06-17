"""
memory/
=======
**Module 7 — Semantic Memory Engine**

Provides vector-based long-term memory for ProjectMind using
``sentence-transformers`` (embedding) and ``ChromaDB`` (vector store).

Public surface
--------------
.. code-block:: python

    from memory import (
        # Data types
        Chunk,
        SearchResult,
        # Core operations
        chunk_python_file,
        embed,
        embed_batch,
        # Store
        MemoryStore,
        # Service
        MemoryUpdater,
        # Search
        search,
        search_by_file,
    )

Contract: :class:`core.interfaces.MemoryEngine` is implemented by
:class:`memory.memory_updater.MemoryUpdater`.
"""

from __future__ import annotations

from memory.chunker import Chunk, ChunkType, chunk_python_file
from memory.embedder import MODEL_NAME, embed, embed_batch
from memory.memory_store import MemoryStore
from memory.memory_updater import MemoryUpdater
from memory.semantic_search import SearchResult, search, search_by_file

__all__ = [
    # Data types
    "Chunk",
    "ChunkType",
    "SearchResult",
    # Functions
    "chunk_python_file",
    "embed",
    "embed_batch",
    "search",
    "search_by_file",
    # Classes
    "MemoryStore",
    "MemoryUpdater",
    # Constants
    "MODEL_NAME",
]
