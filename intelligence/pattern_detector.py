"""
intelligence/pattern_detector.py
=================================
Module 10 — Anti-pattern detection across graph, analyses, and memory.

Public API
----------
- :func:`detect_anti_patterns` — the single entry point.  Returns a list of
  :class:`~intelligence.intelligence_types.Pattern` objects describing every
  anti-pattern found in the current snapshot.

Design contract
---------------
This module is **purely analytical**.  It reads from the graph, from
:class:`~analysis.analysis_types.FileAnalysis` snapshots, and from the
semantic :class:`~memory.memory_store.MemoryStore`.  It never writes
anything — no files, no vault entries, no git operations.

Detected patterns
-----------------
GOD_FILE
    A single source file exposes more than 20 callable functions, making it
    hard to reason about its responsibilities.

CIRCULAR_DEPENDENCY
    Two or more files form an import cycle, preventing safe incremental
    compilation and making refactoring hazardous.

COMPLEXITY_HOTSPOT
    A file whose cyclomatic complexity exceeds 8 **and** that is imported by
    5 or more other files.  High-complexity, high-influence code is the
    riskiest place for bugs to hide.

ORPHAN_MODULE
    A file that neither imports anything nor is imported by anything.  Often
    dead code or a module that was accidentally disconnected.

SEMANTIC_DUPLICATE
    Two functions whose semantic embeddings have a cosine similarity above
    0.92, suggesting one is a near-copy of the other and the two should be
    unified.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import networkx as nx

from analysis.analysis_types import FileAnalysis
from graph.graph_analyzer import find_circular_deps
from intelligence.intelligence_types import Pattern
from core.logger import get_logger

if TYPE_CHECKING:
    from memory.memory_store import MemoryStore

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (named constants so tests can inspect them)
# ---------------------------------------------------------------------------

GOD_FILE_THRESHOLD: int = 20          # > this many functions → GOD_FILE
COMPLEXITY_THRESHOLD: float = 8.0     # cyclomatic complexity > this
HUB_IN_DEGREE_THRESHOLD: int = 5      # imported by >= this many files
SEMANTIC_SIMILARITY_THRESHOLD: float = 0.92  # cosine sim > this → duplicate


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def detect_anti_patterns(
    graph: nx.DiGraph,
    analyses: list[FileAnalysis],
    *,
    store: "MemoryStore | None" = None,
) -> list[Pattern]:
    """Detect anti-patterns in the codebase snapshot.

    Parameters
    ----------
    graph:
        The directed import-dependency graph produced by Module 6.
        Node attributes expected: ``complexity`` (float), ``function_count``
        (int).
    analyses:
        List of :class:`~analysis.analysis_types.FileAnalysis` objects from
        Module 4.  Used for per-function details not stored in the graph.
    store:
        Optional :class:`~memory.memory_store.MemoryStore` instance.  When
        supplied, :data:`SEMANTIC_DUPLICATE` detection is enabled.  When
        *None*, that check is skipped gracefully.

    Returns
    -------
    list[Pattern]
        All detected patterns.  May be empty.  Order is deterministic:
        GOD_FILE → CIRCULAR_DEPENDENCY → COMPLEXITY_HOTSPOT →
        ORPHAN_MODULE → SEMANTIC_DUPLICATE.
    """
    patterns: list[Pattern] = []

    patterns.extend(_detect_god_files(analyses))
    patterns.extend(_detect_circular_dependencies(graph))
    patterns.extend(_detect_complexity_hotspots(graph, analyses))
    patterns.extend(_detect_orphan_modules(graph, analyses))

    if store is not None:
        patterns.extend(_detect_semantic_duplicates(analyses, store=store))

    log.info("[pattern_detector] detected %d pattern(s)", len(patterns))
    return patterns


# ---------------------------------------------------------------------------
# Individual detectors
# ---------------------------------------------------------------------------

def _detect_god_files(analyses: list[FileAnalysis]) -> list[Pattern]:
    """Detect files with more than :data:`GOD_FILE_THRESHOLD` functions."""
    results: list[Pattern] = []
    for fa in analyses:
        count = len(fa.functions)
        if count > GOD_FILE_THRESHOLD:
            evidence = [f"{fa.path}::{fn.name}" for fn in fa.functions]
            results.append(Pattern(
                pattern_type="GOD_FILE",
                severity="high",
                affected_files=[fa.path],
                description=(
                    f"{fa.path!r} defines {count} functions "
                    f"(threshold: {GOD_FILE_THRESHOLD}). "
                    "Consider splitting it into focused sub-modules."
                ),
                evidence=evidence,
            ))
            log.debug("[pattern_detector] GOD_FILE: %s (%d functions)", fa.path, count)
    return results


def _detect_circular_dependencies(graph: nx.DiGraph) -> list[Pattern]:
    """Detect import cycles via :func:`~graph.graph_analyzer.find_circular_deps`."""
    results: list[Pattern] = []
    cycles = find_circular_deps(graph)
    for cycle in cycles:
        evidence = [f"{cycle[i]} → {cycle[(i + 1) % len(cycle)]}"
                    for i in range(len(cycle))]
        results.append(Pattern(
            pattern_type="CIRCULAR_DEPENDENCY",
            severity="critical",
            affected_files=sorted(cycle),
            description=(
                f"Import cycle detected among {len(cycle)} files: "
                + " → ".join(cycle)
                + f" → {cycle[0]}"
            ),
            evidence=evidence,
        ))
        log.debug("[pattern_detector] CIRCULAR_DEPENDENCY: %s", cycle)
    return results


def _detect_complexity_hotspots(
    graph: nx.DiGraph,
    analyses: list[FileAnalysis],
) -> list[Pattern]:
    """Detect files with high complexity that are also widely imported."""
    # Build a lookup: path → FileAnalysis for evidence detail.
    analysis_map: dict[str, FileAnalysis] = {fa.path: fa for fa in analyses}

    results: list[Pattern] = []
    for node, attrs in graph.nodes(data=True):
        complexity: float = float(attrs.get("complexity", 0.0))
        in_degree: int = graph.in_degree(node)

        if complexity > COMPLEXITY_THRESHOLD and in_degree >= HUB_IN_DEGREE_THRESHOLD:
            fa = analysis_map.get(node)
            if fa is not None:
                # Highlight functions that exceed the complexity threshold.
                hot_fns = [
                    f"{node}::{fn.name} (complexity={fn.complexity})"
                    for fn in fa.functions
                    if fn.complexity > COMPLEXITY_THRESHOLD
                ]
                evidence = hot_fns or [f"{node} (aggregate_complexity={complexity:.1f})"]
            else:
                evidence = [f"{node} (aggregate_complexity={complexity:.1f})"]

            importers = sorted(graph.predecessors(node))
            results.append(Pattern(
                pattern_type="COMPLEXITY_HOTSPOT",
                severity="high",
                affected_files=[node],
                description=(
                    f"{node!r} has aggregate complexity {complexity:.1f} "
                    f"(threshold: {COMPLEXITY_THRESHOLD}) and is imported by "
                    f"{in_degree} file(s). A bug here has wide blast radius."
                ),
                evidence=evidence + [f"imported_by: {imp}" for imp in importers],
            ))
            log.debug(
                "[pattern_detector] COMPLEXITY_HOTSPOT: %s (complexity=%.1f, in_degree=%d)",
                node, complexity, in_degree,
            )
    return results


def _detect_orphan_modules(
    graph: nx.DiGraph,
    analyses: list[FileAnalysis],
) -> list[Pattern]:
    """Detect files that are completely disconnected from the import graph."""
    # Only flag nodes that correspond to real analyses (not stubs for
    # external libraries that were added automatically by the graph engine).
    real_paths = {fa.path for fa in analyses}

    results: list[Pattern] = []
    for node in graph.nodes:
        if node not in real_paths:
            continue
        if graph.in_degree(node) == 0 and graph.out_degree(node) == 0:
            results.append(Pattern(
                pattern_type="ORPHAN_MODULE",
                severity="medium",
                affected_files=[node],
                description=(
                    f"{node!r} has no imports and is not imported by any other "
                    "file. It may be dead code or an accidentally disconnected module."
                ),
                evidence=[node],
            ))
            log.debug("[pattern_detector] ORPHAN_MODULE: %s", node)
    return results


def _detect_semantic_duplicates(
    analyses: list[FileAnalysis],
    *,
    store: "MemoryStore",
) -> list[Pattern]:
    """Find pairs of functions whose semantic similarity exceeds the threshold.

    Strategy
    --------
    For each function across all analyses, search the memory store for
    similar chunks.  If a hit from a *different* file scores above
    :data:`SEMANTIC_SIMILARITY_THRESHOLD` and has a ``chunk_type`` of
    ``'function'``, it is a candidate duplicate pair.

    Each unique pair is reported at most once (symmetric deduplication via
    sorted tuple key).
    """
    try:
        from memory.semantic_search import search  # local import to avoid hard dep
    except ImportError:
        log.warning("[pattern_detector] memory.semantic_search not available; skipping SEMANTIC_DUPLICATE")
        return []

    seen_pairs: set[tuple[str, str]] = set()
    results: list[Pattern] = []

    for fa in analyses:
        for fn in fa.functions:
            # Use the function body description as query text.
            query = f"function {fn.name} in {fa.path}: {fn.name}({', '.join(fn.params)})"
            try:
                hits = search(query, store=store, top_k=5)
            except Exception as exc:  # noqa: BLE001
                log.debug("[pattern_detector] semantic search failed for %s::%s: %s",
                          fa.path, fn.name, exc)
                continue

            for hit in hits:
                # Skip hits from the same file.
                if hit.file_path == fa.path:
                    continue
                if hit.score < SEMANTIC_SIMILARITY_THRESHOLD:
                    continue
                # Only consider function-level chunks.
                if hit.metadata.get("chunk_type") not in ("function", "method"):
                    continue

                pair_key = tuple(sorted([
                    f"{fa.path}::{fn.name}",
                    hit.chunk_id,
                ]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                results.append(Pattern(
                    pattern_type="SEMANTIC_DUPLICATE",
                    severity="medium",
                    affected_files=sorted([fa.path, hit.file_path]),
                    description=(
                        f"Function {fn.name!r} in {fa.path!r} is semantically "
                        f"similar (score={hit.score:.3f}) to chunk "
                        f"{hit.chunk_id!r} in {hit.file_path!r}. "
                        "Consider merging or extracting to a shared utility."
                    ),
                    evidence=[
                        f"{fa.path}::{fn.name}",
                        f"{hit.chunk_id} (score={hit.score:.3f})",
                    ],
                ))
                log.debug(
                    "[pattern_detector] SEMANTIC_DUPLICATE: %s::%s ↔ %s (score=%.3f)",
                    fa.path, fn.name, hit.chunk_id, hit.score,
                )

    return results
