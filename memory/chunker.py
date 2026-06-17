"""
memory/chunker.py
=================
Converts a :class:`~analysis.analysis_types.FileAnalysis` (or raw text) into
a flat list of :class:`Chunk` objects that can be embedded and stored in the
vector database.

Chunking strategy
-----------------
- **Python files** (``language == "python"``):
  - One chunk per *function* (content = full extracted source lines).
  - One chunk per *class name* (content = class declaration + name).
  - One *module* chunk covering imports + AI summary.
- **All other languages / plain text**:
  - Sliding window: 500 tokens (≈ words), 50-token overlap.

Chunk ID stability guarantee
-----------------------------
The ``id`` field uses the formula::

    f"{file_path}::{chunk_type}::{name_or_index}"

For a given file + function/class name the ID never changes — safe to use
as an upsert key in ChromaDB.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from analysis.analysis_types import FileAnalysis
from core.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

ChunkType = Literal["function", "class", "module", "text"]

_WINDOW_TOKENS = 500
_OVERLAP_TOKENS = 50


@dataclass
class Chunk:
    """
    A single unit of text ready for embedding and storage.

    Attributes
    ----------
    id:
        Stable identifier — same file + same name/index always yields the
        same id. Used as the upsert key in ChromaDB.
    content:
        The raw text that will be embedded.
    metadata:
        Arbitrary dict stored alongside the vector (file_path, language,
        line ranges, …). Must contain only JSON-serialisable values.
    chunk_type:
        One of ``"function"``, ``"class"``, ``"module"``, ``"text"``.
    """

    id: str
    content: str
    metadata: dict = field(default_factory=dict)
    chunk_type: ChunkType = "text"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_python_file(analysis: FileAnalysis) -> list[Chunk]:
    """
    Produce a stable list of :class:`Chunk` objects from a
    :class:`~analysis.analysis_types.FileAnalysis`.

    For Python source the strategy is:

    1. **Function chunks** — one per ``FunctionInfo`` in
       ``analysis.functions``.  Content is built from the function name,
       parameters, and any call list so the embedding captures semantics
       even without raw source access.
    2. **Class chunks** — one per class name in ``analysis.classes``.
    3. **Module chunk** — imports + AI summary for the whole file.

    For non-Python files the raw ``ai_summary`` (or a placeholder) is
    chunked using a sliding-window approach via
    :func:`_sliding_window_chunks`.

    Parameters
    ----------
    analysis:
        The result of Module 4's static + AI analysis of a single file.

    Returns
    -------
    list[Chunk]
        Ordered list of chunks; never empty (at least one module chunk is
        always produced).
    """
    if analysis.language == "python":
        return _chunk_python(analysis)
    return _chunk_generic(analysis)


# ---------------------------------------------------------------------------
# Internal — Python chunking
# ---------------------------------------------------------------------------

def _chunk_python(analysis: FileAnalysis) -> list[Chunk]:
    chunks: list[Chunk] = []
    fp = analysis.path

    # 1. Function chunks -------------------------------------------------------
    for fn in analysis.functions:
        cid = _make_id(fp, "function", fn.name)
        content_parts = [
            f"def {fn.name}({', '.join(fn.params)}):",
            f"  # lines {fn.line_start}–{fn.line_end}",
            f"  # cyclomatic complexity: {fn.complexity}",
        ]
        if fn.calls:
            content_parts.append(f"  # calls: {', '.join(fn.calls)}")
        if fn.has_docstring:
            content_parts.append("  # has docstring: yes")
        content = "\n".join(content_parts)

        chunks.append(
            Chunk(
                id=cid,
                content=content,
                chunk_type="function",
                metadata={
                    "file_path": fp,
                    "language": "python",
                    "name": fn.name,
                    "line_start": fn.line_start,
                    "line_end": fn.line_end,
                    "complexity": fn.complexity,
                    "has_docstring": fn.has_docstring,
                    "calls": fn.calls,
                    "params": fn.params,
                },
            )
        )

    # 2. Class chunks ----------------------------------------------------------
    for cls_name in analysis.classes:
        cid = _make_id(fp, "class", cls_name)
        content = f"class {cls_name}:  # defined in {Path(fp).name}"
        chunks.append(
            Chunk(
                id=cid,
                content=content,
                chunk_type="class",
                metadata={
                    "file_path": fp,
                    "language": "python",
                    "name": cls_name,
                },
            )
        )

    # 3. Module chunk ----------------------------------------------------------
    cid = _make_id(fp, "module", Path(fp).stem)
    import_text = ", ".join(analysis.imports) if analysis.imports else "(none)"
    summary_text = analysis.ai_summary or "(no summary)"
    anti_text = "; ".join(analysis.anti_patterns) if analysis.anti_patterns else "(none)"
    content = (
        f"File: {fp}\n"
        f"Language: python\n"
        f"Lines of code: {analysis.lines_of_code}\n"
        f"Imports: {import_text}\n"
        f"Summary: {summary_text}\n"
        f"Anti-patterns: {anti_text}"
    )
    chunks.append(
        Chunk(
            id=cid,
            content=content,
            chunk_type="module",
            metadata={
                "file_path": fp,
                "language": "python",
                "lines_of_code": analysis.lines_of_code,
                "imports": analysis.imports,
                "classes": analysis.classes,
                "function_count": len(analysis.functions),
                "analyzed_at": analysis.analyzed_at,
            },
        )
    )

    log.debug(
        "[chunker] python file=%s → %d chunks (%d fn, %d cls, 1 module)",
        fp,
        len(chunks),
        len(analysis.functions),
        len(analysis.classes),
    )
    return chunks


# ---------------------------------------------------------------------------
# Internal — generic / sliding-window chunking
# ---------------------------------------------------------------------------

def _chunk_generic(analysis: FileAnalysis) -> list[Chunk]:
    """
    Produce sliding-window text chunks for non-Python files.

    The text corpus is: AI summary + anti-patterns.  If the content is
    short it is returned as a single chunk.
    """
    fp = analysis.path
    language = analysis.language

    text_parts = []
    if analysis.ai_summary:
        text_parts.append(analysis.ai_summary)
    if analysis.anti_patterns:
        text_parts.append("Issues: " + "; ".join(analysis.anti_patterns))
    if not text_parts:
        # Fallback: use the file path itself so we always have something.
        text_parts.append(f"File: {fp} (language: {language})")

    full_text = "\n".join(text_parts)
    raw_chunks = _sliding_window_chunks(
        full_text,
        window=_WINDOW_TOKENS,
        overlap=_OVERLAP_TOKENS,
    )

    result: list[Chunk] = []
    for idx, window_text in enumerate(raw_chunks):
        cid = _make_id(fp, "text", str(idx))
        result.append(
            Chunk(
                id=cid,
                content=window_text,
                chunk_type="text",
                metadata={
                    "file_path": fp,
                    "language": language,
                    "window_index": idx,
                    "analyzed_at": analysis.analyzed_at,
                },
            )
        )

    log.debug(
        "[chunker] generic file=%s lang=%s → %d chunks",
        fp,
        language,
        len(result),
    )
    return result


def _sliding_window_chunks(
    text: str,
    *,
    window: int = _WINDOW_TOKENS,
    overlap: int = _OVERLAP_TOKENS,
) -> list[str]:
    """
    Split *text* into overlapping token windows.

    Tokens are defined as whitespace-separated words (fast approximation).
    A single-chunk result is returned when ``len(tokens) <= window``.
    """
    tokens = re.split(r"\s+", text.strip())
    if not tokens or tokens == [""]:
        return [""]

    if len(tokens) <= window:
        return [" ".join(tokens)]

    step = max(1, window - overlap)
    windows: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + window, len(tokens))
        windows.append(" ".join(tokens[start:end]))
        if end == len(tokens):
            break
        start += step

    return windows


# ---------------------------------------------------------------------------
# Internal — ID generation
# ---------------------------------------------------------------------------

def _make_id(file_path: str, chunk_type: str, name_or_index: str) -> str:
    """
    Build a stable chunk ID.

    Format::

        "<file_path>::<chunk_type>::<name_or_index>"

    The ID is deterministic: same inputs → same output, always.
    """
    return f"{file_path}::{chunk_type}::{name_or_index}"
