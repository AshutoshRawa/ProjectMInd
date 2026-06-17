"""
memory/embedder.py
==================
Thin, singleton wrapper around the ``sentence-transformers`` model
``all-MiniLM-L6-v2``.

Design decisions
----------------
- The model is loaded **once** at module level on first use (lazy singleton).
  Subsequent calls to :func:`embed` or :func:`embed_batch` reuse the same
  object — no re-loading, no thread-unsafe double initialisation.
- A ``threading.Lock`` guards the one-time load so concurrent callers from
  different threads are safe.
- Batch size defaults to 32, which keeps GPU/CPU memory predictable and
  matches the ``sentence-transformers`` default sweet-spot for MiniLM.
- The module exposes only three public symbols:
    * :func:`embed` — single text → ``list[float]``
    * :func:`embed_batch` — list of texts → ``list[list[float]]``
    * :data:`MODEL_NAME` — the canonical model identifier

Usage
-----
.. code-block:: python

    from memory.embedder import embed, embed_batch

    vec = embed("def hello(): pass")
    vecs = embed_batch(["func a", "func b", "class C"])
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from core.logger import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_NAME: str = "all-MiniLM-L6-v2"
_BATCH_SIZE: int = 32

# ---------------------------------------------------------------------------
# Module-level singleton state
# ---------------------------------------------------------------------------

_model: "SentenceTransformer | None" = None
_model_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal loader
# ---------------------------------------------------------------------------

def _get_model() -> "SentenceTransformer":
    """
    Return the singleton :class:`~sentence_transformers.SentenceTransformer`
    instance, loading it on the first call.

    Thread-safe: the lock ensures only one thread initialises the model
    even if multiple callers arrive simultaneously.
    """
    global _model  # noqa: PLW0603

    if _model is not None:
        return _model

    with _model_lock:
        # Double-checked locking — re-test inside the lock.
        if _model is not None:
            return _model

        log.info("[embedder] loading model '%s' (first call) …", MODEL_NAME)
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Run: pip install sentence-transformers"
            ) from exc

        _model = SentenceTransformer(MODEL_NAME)
        # get_embedding_dimension() is the current API;
        # fall back to the deprecated name for older sentence-transformers.
        _dim_fn = getattr(
            _model,
            "get_embedding_dimension",
            getattr(_model, "get_sentence_embedding_dimension", lambda: "?"),
        )
        log.info(
            "[embedder] model '%s' loaded — embedding dim=%s",
            MODEL_NAME,
            _dim_fn(),
        )

    return _model


def _reset_for_testing() -> None:
    """Clear the cached model so tests can isolate singleton state."""
    global _model  # noqa: PLW0603

    with _model_lock:
        _model = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def embed(text: str) -> list[float]:
    """
    Embed a single piece of *text* using the singleton MiniLM model.

    Parameters
    ----------
    text:
        Any UTF-8 string.  Empty strings are allowed and will produce a
        zero-like vector (model-dependent behaviour).

    Returns
    -------
    list[float]
        Dense embedding vector (384 dimensions for all-MiniLM-L6-v2).
    """
    model = _get_model()
    # encode() returns a numpy array; .tolist() converts to plain Python list.
    vector = model.encode(text, batch_size=1, show_progress_bar=False)
    return vector.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed a batch of texts efficiently.

    Texts are processed in chunks of :data:`_BATCH_SIZE` (32) so that
    memory usage stays bounded regardless of input length.

    Parameters
    ----------
    texts:
        List of UTF-8 strings.  Empty list returns ``[]``.

    Returns
    -------
    list[list[float]]
        One vector per input text, preserving order.
    """
    if not texts:
        return []

    model = _get_model()
    log.debug(
        "[embedder] embed_batch: %d texts, batch_size=%d",
        len(texts),
        _BATCH_SIZE,
    )
    vectors = model.encode(
        texts,
        batch_size=_BATCH_SIZE,
        show_progress_bar=False,
    )
    # vectors is a 2-D numpy array; convert each row to a Python list.
    return [row.tolist() for row in vectors]
